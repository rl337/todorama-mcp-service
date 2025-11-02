"""
Distributed tracing for TODO service using OpenTelemetry.

Provides:
- OpenTelemetry instrumentation for FastAPI
- Database operation tracing
- Request tracing across services
- Integration with Jaeger for visualization
"""
import os
import logging
from typing import Optional, Dict, Any, Callable
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
try:
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter
    JAEGER_AVAILABLE = True
except ImportError:
    JaegerExporter = None
    JAEGER_AVAILABLE = False
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

logger = logging.getLogger(__name__)

# Global tracer
_tracer: Optional[trace.Tracer] = None
_service_name = os.getenv("OTEL_SERVICE_NAME", "todo-mcp-service")
_otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
_jaeger_endpoint = os.getenv("JAEGER_ENDPOINT", "http://localhost:14268/api/traces")
_use_jaeger = os.getenv("OTEL_EXPORTER_JAEGER_ENABLED", "false").lower() == "true"
_use_otlp = os.getenv("OTEL_EXPORTER_OTLP_ENABLED", "true").lower() == "true"
_enable_console = os.getenv("OTEL_CONSOLE_EXPORTER_ENABLED", "false").lower() == "true"


def setup_tracing() -> None:
    """Initialize OpenTelemetry tracing for the service."""
    global _tracer
    
    if _tracer is not None:
        logger.warning("Tracing already initialized")
        return
    
    logger.info(
        "Initializing OpenTelemetry tracing",
        extra={
            "service_name": _service_name,
            "otlp_endpoint": _otlp_endpoint,
            "jaeger_endpoint": _jaeger_endpoint,
            "use_otlp": _use_otlp,
            "use_jaeger": _use_jaeger,
            "enable_console": _enable_console,
        }
    )
    
    # Create resource with service information
    resource = Resource.create({
        "service.name": _service_name,
        "service.version": os.getenv("SERVICE_VERSION", "0.1.0"),
        "deployment.environment": os.getenv("ENVIRONMENT", "development"),
    })
    
    # Create tracer provider
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)
    
    # Add span processors (exporters)
    span_processors = []
    
    # OTLP exporter (for Jaeger, Tempo, etc. via OTLP)
    if _use_otlp:
        try:
            otlp_exporter = OTLPSpanExporter(
                endpoint=_otlp_endpoint,
                insecure=True,  # Use TLS in production
            )
            span_processors.append(BatchSpanProcessor(otlp_exporter))
            logger.info("OTLP exporter configured", extra={"endpoint": _otlp_endpoint})
        except Exception as e:
            logger.warning("Failed to configure OTLP exporter", exc_info=True)
    
    # Jaeger exporter (direct) - optional if package not installed
    if _use_jaeger:
        if not JAEGER_AVAILABLE:
            logger.warning("Jaeger exporter requested but opentelemetry-exporter-jaeger not installed")
        else:
            try:
                jaeger_exporter = JaegerExporter(
                    agent_host_name=os.getenv("JAEGER_AGENT_HOST", "localhost"),
                    agent_port=int(os.getenv("JAEGER_AGENT_PORT", "6831")),
                    collector_endpoint=_jaeger_endpoint,
                )
                span_processors.append(BatchSpanProcessor(jaeger_exporter))
                logger.info("Jaeger exporter configured", extra={"endpoint": _jaeger_endpoint})
            except Exception as e:
                logger.warning("Failed to configure Jaeger exporter", exc_info=True)
    
    # Console exporter (for debugging)
    if _enable_console:
        console_exporter = ConsoleSpanExporter()
        span_processors.append(BatchSpanProcessor(console_exporter))
        logger.info("Console exporter enabled")
    
    # Register span processors
    for processor in span_processors:
        provider.add_span_processor(processor)
    
    # Get tracer
    _tracer = trace.get_tracer(__name__)
    
    logger.info("OpenTelemetry tracing initialized successfully")


def instrument_fastapi(app) -> None:
    """Instrument FastAPI application with OpenTelemetry."""
    try:
        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI instrumentation enabled")
    except Exception as e:
        logger.error("Failed to instrument FastAPI", exc_info=True)


def instrument_database() -> None:
    """Instrument database operations with OpenTelemetry."""
    try:
        SQLite3Instrumentor().instrument()
        logger.info("SQLite3 instrumentation enabled")
    except Exception as e:
        logger.error("Failed to instrument SQLite3", exc_info=True)


def instrument_httpx() -> None:
    """Instrument HTTPX client with OpenTelemetry."""
    try:
        HTTPXClientInstrumentor().instrument()
        logger.info("HTTPX instrumentation enabled")
    except Exception as e:
        logger.error("Failed to instrument HTTPX", exc_info=True)


def get_tracer() -> trace.Tracer:
    """Get the global tracer instance."""
    global _tracer
    if _tracer is None:
        # Initialize if not already done
        setup_tracing()
    return _tracer or trace.get_tracer(__name__)


@contextmanager
def trace_span(
    name: str,
    attributes: Optional[Dict[str, Any]] = None,
    kind: trace.SpanKind = trace.SpanKind.INTERNAL
):
    """
    Context manager for creating a trace span.
    
    Args:
        name: Name of the span
        attributes: Optional attributes to add to the span
        kind: Span kind (INTERNAL, SERVER, CLIENT, etc.)
    
    Example:
        with trace_span("database.query", {"table": "tasks"}):
            db.execute_query(...)
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(name, kind=kind) as span:
        if attributes:
            for key, value in attributes.items():
                if value is not None:
                    # Convert value to appropriate type
                    if isinstance(value, (str, int, float, bool)):
                        span.set_attribute(key, value)
                    else:
                        span.set_attribute(key, str(value))
        
        try:
            yield span
        except Exception as e:
            # Record exception in span
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            raise


def trace_function(
    func: Callable,
    span_name: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None
):
    """
    Decorator to trace a function call.
    
    Args:
        func: Function to trace
        span_name: Optional custom span name (defaults to function name)
        attributes: Optional attributes to add to the span
    
    Example:
        @trace_function
        def process_task(task_id: int):
            ...
    """
    def decorator(*args, **kwargs):
        name = span_name or f"{func.__module__}.{func.__name__}"
        with trace_span(name, attributes):
            return func(*args, **kwargs)
    
    return decorator


def add_span_attribute(key: str, value: Any) -> None:
    """Add an attribute to the current active span."""
    span = trace.get_current_span()
    if span:
        if isinstance(value, (str, int, float, bool)):
            span.set_attribute(key, value)
        else:
            span.set_attribute(key, str(value))


def add_span_event(name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
    """Add an event to the current active span."""
    span = trace.get_current_span()
    if span:
        span.add_event(name, attributes or {})


def set_span_status(status_code: trace.StatusCode, description: Optional[str] = None) -> None:
    """Set the status of the current active span."""
    span = trace.get_current_span()
    if span:
        span.set_status(trace.Status(status_code, description))
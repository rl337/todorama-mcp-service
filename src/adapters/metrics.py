"""
Adapter for metrics library (Prometheus).
Isolates Prometheus-specific imports to make library replacement easier.
"""
try:
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain"
    generate_latest = None


class MetricsAdapter:
    """Adapter for metrics operations."""
    
    def __init__(self):
        self.available = METRICS_AVAILABLE
        self.CONTENT_TYPE_LATEST = CONTENT_TYPE_LATEST
        self.generate_latest = generate_latest if METRICS_AVAILABLE else self._fallback_generate
    
    def _fallback_generate(self):
        """Fallback when Prometheus is not available."""
        return "# Prometheus metrics not available\n"
    
    def get_content_type(self):
        """Get the content type for metrics response."""
        return self.CONTENT_TYPE_LATEST
    
    def generate_metrics_response(self):
        """Generate metrics response."""
        return self.generate_latest()


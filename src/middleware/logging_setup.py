"""
Logging configuration and setup.
"""
import logging
from adapters.http_framework import HTTPFrameworkAdapter


class RequestIDFilter(logging.Filter):
    """Logging filter to add request ID to log records."""
    
    def filter(self, record):
        """Add request_id to log record if available."""
        if not hasattr(record, 'request_id'):
            record.request_id = getattr(record, 'request_id', '-')
        return True


class SafeFormatter(logging.Formatter):
    """Safe formatter that handles missing request_id gracefully."""
    
    def format(self, record):
        """Format log record, handling missing request_id."""
        if not hasattr(record, 'request_id'):
            record.request_id = '-'
        try:
            return super().format(record)
        except KeyError:
            # If request_id is still missing in format string, set it
            record.request_id = '-'
            return super().format(record)


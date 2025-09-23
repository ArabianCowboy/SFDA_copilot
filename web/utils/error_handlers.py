"""
Enhanced error handling for embedding operations and configuration management.
Provides centralized error handling, logging, and fallback mechanisms.
"""

import logging
from typing import Optional, Dict, Any, Union, List
from functools import wraps
import traceback

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EmbeddingErrorHandler:
    """
    Centralized error handling for embedding operations.
    Provides consistent error handling and logging across all embedding operations.
    """
    
    @staticmethod
    def handle_embedding_error(error: Exception, context: str, fallback: Any = None) -> Any:
        """
        Handle embedding errors with logging and fallback.
        
        Args:
            error: The exception that occurred
            context: Context where the error occurred
            fallback: Fallback value to return if provided
            
        Returns:
            Fallback value or re-raises the exception
        """
        error_msg = f"Embedding error in {context}: {str(error)}"
        logger.error(error_msg)
        logger.debug(f"Error traceback: {traceback.format_exc()}")
        
        # Check if we should re-raise the exception
        try:
            from .config_loader import ConfigLoader
            config = ConfigLoader().config
            strict_mode = config.get("validation", {}).get("strict_mode", False)
            
            if strict_mode:
                logger.error(f"Strict mode enabled in {context}. Re-raising exception.")
                raise error
                
        except Exception:
            # If config loading fails, use default behavior
            pass
        
        # Return fallback if provided
        if fallback is not None:
            logger.info(f"Using fallback for {context}")
            return fallback
        
        # Re-raise the exception if no fallback provided
        raise error
    
    @staticmethod
    def validate_config(config: Dict[str, Any], section: str) -> bool:
        """
        Validate configuration section.
        
        Args:
            config: Configuration dictionary
            section: Section to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        if section not in config:
            logger.warning(f"Missing configuration section: {section}")
            return False
        
        if not isinstance(config[section], dict):
            logger.warning(f"Configuration section {section} is not a dictionary")
            return False
        
        return True
    
    @staticmethod
    def validate_embedding_config(config: Dict[str, Any]) -> bool:
        """
        Validate embedding-specific configuration.
        
        Args:
            config: Configuration dictionary
            
        Returns:
            bool: True if valid, False otherwise
        """
        # Check embedding section
        if not EmbeddingErrorHandler.validate_config(config, "embedding"):
            return False
        
        # Check embedding dimensions
        dimensions = config["embedding"].get("dimensions", {})
        if not isinstance(dimensions, dict):
            logger.warning("Embedding dimensions must be a dictionary")
            return False
        
        # Validate each dimension value
        for provider, dimension in dimensions.items():
            if not isinstance(dimension, int) or dimension <= 0:
                logger.warning(f"Invalid dimension for provider {provider}: {dimension}")
                return False
        
        # Check search_engine section
        if not EmbeddingErrorHandler.validate_config(config, "search_engine"):
            return False
        
        # Check embedding type
        embedding_type = config["search_engine"].get("embedding_type")
        if embedding_type not in dimensions:
            logger.warning(f"Unknown embedding type: {embedding_type}")
            return False
        
        return True


class ConfigErrorHandler:
    """
    Error handling for configuration operations.
    """
    
    @staticmethod
    def handle_config_error(error: Exception, context: str, config: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Handle configuration errors with logging and fallback.
        
        Args:
            error: The exception that occurred
            context: Context where the error occurred
            config: Current configuration (optional)
            
        Returns:
            Fallback configuration or re-raises the exception
        """
        error_msg = f"Configuration error in {context}: {str(error)}"
        logger.error(error_msg)
        logger.debug(f"Error traceback: {traceback.format_exc()}")
        
        # Return default configuration if provided
        if config is not None:
            logger.info(f"Using default configuration for {context}")
            return config
        
        # Re-raise the exception if no fallback provided
        raise error


class ServiceErrorHandler:
    """
    Error handling for service operations.
    """
    
    @staticmethod
    def handle_service_error(error: Exception, service_name: str, operation: str) -> None:
        """
        Handle service errors with logging.
        
        Args:
            error: The exception that occurred
            service_name: Name of the service
            operation: Operation being performed
        """
        error_msg = f"Service error in {service_name} during {operation}: {str(error)}"
        logger.error(error_msg)
        logger.debug(f"Error traceback: {traceback.format_exc()}")


# Decorators for safe operations
def safe_embedding_operation(operation_name: str):
    """
    Decorator for safe embedding operations with error handling.
    Provides consistent error handling and logging across all embedding operations.
    
    Args:
        operation_name: Name of the operation for logging purposes
        
    Returns:
        Decorator function
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                context = f"{operation_name} in {func.__name__}"
                return EmbeddingErrorHandler.handle_embedding_error(
                    e, context, kwargs.get('fallback')
                )
        return wrapper
    return decorator


def safe_config_operation(operation_name: str):
    """
    Decorator for safe configuration operations with error handling.
    
    Args:
        operation_name: Name of the operation for logging purposes
        
    Returns:
        Decorator function
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                context = f"{operation_name} in {func.__name__}"
                config = kwargs.get('config', {})
                return ConfigErrorHandler.handle_config_error(e, context, config)
        return wrapper
    return decorator


def safe_service_operation(service_name: str):
    """
    Decorator for safe service operations with error handling.
    
    Args:
        service_name: Name of the service for logging purposes
        
    Returns:
        Decorator function
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                operation = func.__name__
                ServiceErrorHandler.handle_service_error(e, service_name, operation)
                # For service operations, we typically don't return a fallback
                # but could be extended to do so if needed
                raise
        return wrapper
    return decorator


# Utility functions for error recovery
def recover_from_embedding_error(error: Exception, operation: str, fallback_value: Any = None) -> Any:
    """
    Utility function to recover from embedding errors.
    
    Args:
        error: The exception that occurred
        operation: Operation being performed
        fallback_value: Value to return as fallback
        
    Returns:
        Fallback value or re-raises the exception
    """
    logger.warning(f"Recovering from embedding error in {operation}: {str(error)}")
    
    if fallback_value is not None:
        logger.info(f"Using fallback value for {operation}")
        return fallback_value
    
    # If no fallback provided, re-raise
    raise error


def log_and_continue(func):
    """
    Decorator that logs errors but continues execution.
    Useful for non-critical operations.
    
    Args:
        func: Function to decorate
        
    Returns:
        Decorated function
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {str(e)}")
            logger.debug(f"Error traceback: {traceback.format_exc()}")
            # Return None or appropriate default value
            return None
    return wrapper
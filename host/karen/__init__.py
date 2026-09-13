"""Karen package – host AI pipeline."""

__all__ = ["KarenPipeline"]
__version__ = "0.1.0"


def __getattr__(name: str):
    if name == "KarenPipeline":
        from .pipeline import KarenPipeline
        return KarenPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

import uvicorn
import argparse
import sys
from flashcard.settings import settings

def main():
    """Entry point for production run"""
    uvicorn.run(
        "flashcard.api.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=False
    )

def dev():
    """Entry point for development run with reload"""
    uvicorn.run(
        "flashcard.api.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=True
    )

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "dev":
        dev()
    else:
        main()

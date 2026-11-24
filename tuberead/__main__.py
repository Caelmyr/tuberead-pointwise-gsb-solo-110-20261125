import os

from waitress import serve

from .server import create_app


if __name__ == "__main__":
    serve(create_app(), host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8000")), threads=4)

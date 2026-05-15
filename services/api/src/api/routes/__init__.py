"""HTTP route modules for the api service.

Each submodule exports a ``router: APIRouter`` that ``api.main`` includes.
Keep one router per feature; share dependencies via ``api.dependencies``.
"""

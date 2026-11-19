from .scene import SceneProvider
from .vox import VoxProvider

PROVIDERS = {
    p.key: p for p in [
        SceneProvider(),
        VoxProvider("vox_almaza", "City Centre Almaza", "VOX Cinemas – City Centre Almaza", "VOX Almaza"),
    ]
}

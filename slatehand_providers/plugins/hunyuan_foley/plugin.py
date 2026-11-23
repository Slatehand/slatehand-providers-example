"""安装 HunyuanVideo-Foley XXL 插件。"""

from core.model_providers.http import HttpTransport
from core.model_providers.registry import PluginInstance

from .manifest import MANIFEST
from .provider import HunyuanFoleyProvider


def plugin_instance(endpoint: str, transport: HttpTransport | None = None) -> PluginInstance:
    provider = HunyuanFoleyProvider(endpoint, transport)
    return PluginInstance(MANIFEST, endpoint=endpoint, recipes={MANIFEST.recipes[0].id: provider})

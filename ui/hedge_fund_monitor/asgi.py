#!/usr/bin/env python3
"""
ASGI config for hedge_fund_monitor project.
Enables Django Channels for WebSocket real-time updates
"""

import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hedge_fund_monitor.settings')

django_asgi_app = get_asgi_application()

# Import WebSocket routing after Django is set up
from monitor import routing

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(
                routing.websocket_urlpatterns
            )
        )
    ),
})

#!/usr/bin/env python3
"""
Simple test to check if the module imports correctly and has endpoints.
"""

import inspect
from growth.adapters.freelance_pipeline import router

# Check what endpoints are defined in the router
print("Router routes:")
for route in router.routes:
    print(f"  {route.path} - {route.methods}")

print("\nRouter tags:", router.tags)
print("\nRouter prefix:", router.prefix)

# Check if health endpoint exists
health_exists = any(route.path == "/health" for route in router.routes)
print(f"\nHealth endpoint exists: {health_exists}")

# Try to import and see what we get
print("\nModule imported successfully!")
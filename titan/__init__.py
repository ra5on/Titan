"""Titan — NAS management on Debian with signed system updates."""

__version__ = "0.8.3"
__release_stage__ = "stable"

# This release adds host-agent APIs. Older agents must receive the full system
# update before this interface; the standalone web publisher refuses it.
__web_update_standalone__ = False

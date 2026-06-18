"""Baidu Netdisk sync integration for cdx-brain cognitive products.

Provides bdpan-based upload of pipeline_state.json, cold.db,
and federated cognitive artifacts to Baidu Pan for 好妹 (cloud VM) access.
"""

from cdx_brain.sync.bdpan import sync_to_bdpan, sync_all_cognitive, BDPAN_REMOTE_BASE

__all__ = ["sync_to_bdpan", "sync_all_cognitive", "BDPAN_REMOTE_BASE"]



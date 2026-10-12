"""Index the post's new/changed questions before marking processing complete."""

from ...embedding.backfill import backfill_embeddings


async def run(state, *, trace=None):
    if state.get("skip_reason"):
        return {"current_node": "indexer"}
    stats = await backfill_embeddings(
        post_ids=[state["post_id"]], processing_owner=state.get("processing_owner")
    )
    return {"current_node": "indexer", "indexed": stats.embedded}

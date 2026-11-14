"""Read revocations over immutable published ancestry, never active defaults."""


def registry_revocations(conn, release_id):
    # Each workspace stores its exact base bundle at creation. UNION also
    # bounds traversal if a damaged database contains a bundle cycle.
    return [dict(row) for row in conn.execute("""
        WITH RECURSIVE lineage(release_id) AS (
            SELECT ?
            UNION
            SELECT json_extract(CAST(parent.payload AS TEXT), '$.registry_ref.id')
            FROM registry_bundles child
            JOIN lineage ON json_extract(CAST(child.payload AS TEXT), '$.registry_ref.id') = lineage.release_id
            JOIN registry_bundles parent ON parent.bundle_id = json_extract(CAST(child.payload AS TEXT), '$.base_bundle_id')
        )
        SELECT revocations.* FROM revocations
        JOIN lineage ON lineage.release_id = revocations.release_id
        ORDER BY revocations.revision
    """, (release_id,))]

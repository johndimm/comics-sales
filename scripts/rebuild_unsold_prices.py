from app.db import get_conn


def main():
    conn = get_conn()
    cur = conn.cursor()

    # Clear prior suggestions
    cur.execute("DELETE FROM price_suggestions")

    # Build suggestions ONLY for unsold inventory in target classes
    cur.execute(
        """
        INSERT INTO price_suggestions (comic_id, quick_sale, market_price, premium_price, confidence, basis_count, updated_at)
        SELECT
          c.id,
          ROUND(AVG(mc.price) * 0.90, 2) AS quick_sale,
          ROUND(AVG(mc.price), 2) AS market_price,
          ROUND(AVG(mc.price) * 1.15, 2) AS premium_price,
          CASE
            WHEN COUNT(*) >= 8 THEN 'high'
            WHEN COUNT(*) >= 3 THEN 'medium'
            ELSE 'low'
          END AS confidence,
          COUNT(*) AS basis_count,
          CURRENT_TIMESTAMP
        FROM comics c
        JOIN market_comps mc
          ON mc.listing_type = 'sold'
         AND mc.title = c.title
         AND (mc.issue = c.issue OR mc.issue IS NULL)
        WHERE c.status IN ('unlisted','drafted')
          AND c.sold_price IS NULL
          AND (
            (c.cgc_cert IS NOT NULL AND TRIM(c.cgc_cert) <> '')
            OR ((c.cgc_cert IS NULL OR TRIM(c.cgc_cert)='') AND c.community_url IS NOT NULL AND TRIM(c.community_url) <> '')
          )
        GROUP BY c.id
        """
    )

    conn.commit()

    stats = conn.execute(
        """
        SELECT
          SUM(CASE WHEN c.status IN ('unlisted','drafted') AND c.sold_price IS NULL
                    AND c.cgc_cert IS NOT NULL AND TRIM(c.cgc_cert)<>'' THEN 1 ELSE 0 END) AS unsold_slabbed,
          SUM(CASE WHEN c.status IN ('unlisted','drafted') AND c.sold_price IS NULL
                    AND (c.cgc_cert IS NULL OR TRIM(c.cgc_cert)='')
                    AND c.community_url IS NOT NULL AND TRIM(c.community_url)<>'' THEN 1 ELSE 0 END) AS unsold_raw_community,
          (SELECT COUNT(*) FROM price_suggestions) AS priced_target
        FROM comics c
        """
    ).fetchone()

    conn.close()
    print(f"unsold_slabbed={stats[0]} unsold_raw_community={stats[1]} priced_target={stats[2]}")


if __name__ == "__main__":
    main()

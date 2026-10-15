from iowa_lakehouse.analytics import annual_sales, item_month_panel, monthly_sales, recent_months


def test_windows_have_exact_calendar_month_counts(spark):
    facts = spark.sql("""SELECT d AS sale_date, 10.0 AS sale_dollars, 1 AS sale_bottles
        FROM (SELECT explode(sequence(DATE '2022-01-01', DATE '2025-10-01', INTERVAL 1 MONTH)) d)""")
    assert [recent_months(facts, n).count() for n in (3, 6, 12, 36)] == [3, 6, 12, 36]


def test_yoy_uses_same_calendar_month_despite_gaps(spark):
    facts = spark.sql("""SELECT d AS sale_date, year(d)*100.0 + month(d) AS sale_dollars, 1 AS sale_bottles
        FROM (SELECT explode(sequence(DATE '2024-01-01', DATE '2025-10-01', INTERVAL 1 MONTH)) d)
        WHERE d <> DATE '2025-05-01'""")
    result = monthly_sales(facts).where("month_start=DATE '2025-10-01'").first()
    assert result.sales_prev_year == 202410
    assert monthly_sales(facts).where("month_start=DATE '2024-10-01'").first().sales_prev_year is None


def test_annual_completeness_is_explicit(spark):
    facts = spark.sql(
        "SELECT DATE '2024-12-31' sale_date, 100.0 sale_dollars UNION ALL SELECT DATE '2025-05-23', 50.0"
    )
    assert [r.year for r in annual_sales(facts, complete_through_year=2024).collect()] == [2024]


def test_item_panel_does_not_split_attribute_versions(spark):
    facts = spark.sql("""SELECT 'usa' country, 1 item_no, DATE '2025-01-01' sale_date,
        'old description' item_desc, 2 sale_bottles, 20.0 sale_dollars
        UNION ALL SELECT 'usa', 1, DATE '2025-01-15', 'new description', 3, 30.0""")
    result = item_month_panel(facts).collect()
    assert len(result) == 1 and result[0].qty_bottles == 5 and result[0].unit_price_usd == 10

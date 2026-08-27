"""Tests for EqSQL Integration in query_rewriter and scirpy_bridge."""
import unittest
from unittest.mock import patch, MagicMock

from src.scirpy_bridge import eqsql_optimize_query
from src.query_rewriter import QueryRewriter

class TestEqSQLIntegration(unittest.TestCase):
    
    def setUp(self):
        import src.scirpy_bridge as sb
        sb._gateway = None
        sb._gateway_proc = None

    @patch('src.scirpy_bridge.time.sleep')
    @patch('src.scirpy_bridge.JavaGateway')
    @patch('src.scirpy_bridge.subprocess.Popen')
    def test_eqsql_optimize_query_success(self, mock_popen, mock_gateway, mock_sleep):
        mock_app = mock_gateway.return_value.entry_point
        mock_app.optimizeQuery.return_value = "SELECT * FROM optimized_table"
        
        result = eqsql_optimize_query("SELECT * FROM table", "sqlite")
        self.assertEqual(result, "SELECT * FROM optimized_table")
        
    @patch('src.scirpy_bridge.time.sleep')
    @patch('src.scirpy_bridge.JavaGateway')
    @patch('src.scirpy_bridge.subprocess.Popen')
    def test_eqsql_optimize_query_fallback_on_exception(self, mock_popen, mock_gateway, mock_sleep):
        mock_app = mock_gateway.return_value.entry_point
        mock_app.optimizeQuery.side_effect = Exception("EqSQL Error")
        
        original_sql = "SELECT * FROM table"
        result = eqsql_optimize_query(original_sql, "sqlite")
        self.assertEqual(result, original_sql)

    @patch('src.scirpy_bridge.time.sleep')
    @patch('src.scirpy_bridge.JavaGateway')
    @patch('src.scirpy_bridge.subprocess.Popen')
    def test_gateway_reuse(self, mock_popen, mock_gateway, mock_sleep):
        mock_app = mock_gateway.return_value.entry_point
        mock_app.optimizeQuery.return_value = "SELECT 1"
        
        eqsql_optimize_query("SELECT * FROM t1", "sqlite")
        mock_popen.assert_called_once()
        mock_gateway.assert_called_once()
        
        eqsql_optimize_query("SELECT * FROM t2", "sqlite")
        self.assertEqual(mock_popen.call_count, 1)
        self.assertEqual(mock_gateway.call_count, 1)
        
    @patch('src.query_rewriter.eqsql_optimize_query')
    def test_query_rewriter_uses_eqsql(self, mock_eqsql):
        mock_eqsql.return_value = "SELECT * FROM optimized_table WHERE id = ?"
        rewriter = QueryRewriter()
        
        result = rewriter.rewrite_for_batch("SELECT * FROM table WHERE id = ?", "id", "sqlite")
        self.assertEqual(result, "SELECT id, * FROM optimized_table WHERE id IN ({})")
        mock_eqsql.assert_called_once_with("SELECT * FROM table WHERE id = ?", "sqlite")

    @patch('src.query_rewriter.eqsql_optimize_query')
    def test_query_rewriter_fallback(self, mock_eqsql):
        # When eqsql returns the same query
        original_sql = "SELECT * FROM table WHERE id = ?"
        mock_eqsql.return_value = original_sql
        
        rewriter = QueryRewriter()
        result = rewriter.rewrite_for_batch(original_sql, "id", "sqlite")
        self.assertEqual(result, "SELECT id, * FROM table WHERE id IN ({})")

    @patch('src.query_rewriter.eqsql_optimize_query')
    def test_query_rewriter_scalar_aggregate(self, mock_eqsql):
        # GROUP BY query from eqsql
        mock_eqsql.return_value = "SELECT count(*), category FROM parts WHERE category = ? GROUP BY category"
        rewriter = QueryRewriter()
        
        result = rewriter.rewrite_for_batch("SELECT count(*) FROM parts WHERE category = ?", "category", "sqlite")
        self.assertEqual(result, "SELECT count(*), category FROM parts WHERE category IN ({}) GROUP BY category")
        
    @patch('src.query_rewriter.eqsql_optimize_query')
    def test_query_rewriter_named_parameters(self, mock_eqsql):
        # Named parameters preserve %(category)s format
        mock_eqsql.return_value = "SELECT count(*), category FROM parts WHERE category = %(category)s GROUP BY category"
        rewriter = QueryRewriter()
        
        result = rewriter.rewrite_for_batch("SELECT count(*) FROM parts WHERE category = %(category)s", "category", "postgres")
        self.assertEqual(result, "SELECT count(*), category FROM parts WHERE category = ANY(%(category)s) GROUP BY category")

    def test_live_jvm_optimize_query(self):
        import src.scirpy_bridge as sb
        # Ensure clean state
        if sb._gateway:
            sb._shutdown_gateway()

        sql1 = "SELECT count(*) FROM parts WHERE category = ?"
        opt1 = eqsql_optimize_query(sql1, "sqlite")
        self.assertIn("GROUP BY category", opt1)

        sql2 = "SELECT sum(price) FROM parts WHERE category = ?"
        opt2 = eqsql_optimize_query(sql2, "sqlite")
        self.assertIn("GROUP BY category", opt2)

        sql3 = "SELECT avg(rating) FROM parts WHERE category = ?"
        opt3 = eqsql_optimize_query(sql3, "sqlite")
        self.assertIn("GROUP BY category", opt3)

        sql4 = "SELECT count(a) + 1 FROM parts WHERE category = ?"
        opt4 = eqsql_optimize_query(sql4, "sqlite")
        self.assertEqual(opt4, sql4)

        sb._shutdown_gateway()

if __name__ == '__main__':
    unittest.main()

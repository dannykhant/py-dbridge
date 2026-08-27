package dbridge.eqsql;

import java.util.ArrayList;
import java.util.List;

public class OptimizeQueryHarness {
    public static void main(String[] args) {
        System.out.println("Running OptimizeQueryHarness...");
        List<String> failures = new ArrayList<>();

        // SQL 1: postgres with GROUP BY
        String sql1 = "SELECT id, count(*) FROM orders WHERE user_id = ? GROUP BY id";
        String out1 = EqSQLHelper.optimizeQuery(sql1, "postgres");
        System.out.println("SQL 1: " + out1);
        check(failures, "SQL 1 (postgres group by)", out1,
              "SELECT id, count(*) FROM orders WHERE user_id = ANY(%s) GROUP BY id".equals(out1));

        // SQL 2: sqlite with GROUP BY
        String sql2 = "SELECT id, count(*) FROM orders WHERE user_id = ? GROUP BY id";
        String out2 = EqSQLHelper.optimizeQuery(sql2, "sqlite");
        System.out.println("SQL 2: " + out2);
        check(failures, "SQL 2 (sqlite group by)", out2,
              "SELECT id, count(*) FROM orders WHERE user_id IN ({}) GROUP BY id".equals(out2));

        // SQL 3: AND with constant predicate
        String sql3 = "SELECT a FROM t WHERE x = ? AND y = 'foo'";
        String out3 = EqSQLHelper.optimizeQuery(sql3, "sqlite");
        System.out.println("SQL 3: " + out3);
        check(failures, "SQL 3 (AND constant)", out3,
              "SELECT a FROM t WHERE x IN ({}) AND y = 'foo'".equals(out3));

        // SQL 4: OR with two parameters
        String sql4 = "SELECT a FROM t WHERE x = ? OR b = ?";
        String out4 = EqSQLHelper.optimizeQuery(sql4, "postgres");
        System.out.println("SQL 4: " + out4);
        check(failures, "SQL 4 (OR two params)", out4,
              "SELECT a FROM t WHERE x = ANY(%s) OR b = ANY(%s)".equals(out4));

        // SQL 5: named postgres parameter
        String sql5 = "SELECT count(*) FROM parts WHERE category = %(category)s";
        String out5 = EqSQLHelper.optimizeQuery(sql5, "postgres");
        System.out.println("SQL 5: " + out5);
        check(failures, "SQL 5 (named param)", out5,
              "SELECT count(*) FROM parts WHERE category = ANY(%(category)s)".equals(out5));

        // SQL 6: integer constant predicate
        String sql6 = "SELECT a FROM t WHERE status = 1";
        String out6 = EqSQLHelper.optimizeQuery(sql6, "sqlite");
        System.out.println("SQL 6: " + out6);
        check(failures, "SQL 6 (int const)", out6,
              "SELECT a FROM t WHERE status = 1".equals(out6));

        // SQL 7: <> comparison
        String sql7 = "SELECT a FROM t WHERE x <> 5";
        String out7 = EqSQLHelper.optimizeQuery(sql7, "sqlite");
        System.out.println("SQL 7: " + out7);
        check(failures, "SQL 7 (<> comparison)", out7,
              "SELECT a FROM t WHERE x <> 5".equals(out7));

        // C1: Non-= comparison with param preserves parameter without malformed = ANY / IN
        String sqlC1 = "SELECT a FROM t WHERE x < ? AND y = ?";
        String outC1 = EqSQLHelper.optimizeQuery(sqlC1, "sqlite");
        System.out.println("SQL C1: " + outC1);
        check(failures, "SQL C1 (non-equality param)", outC1,
              "SELECT a FROM t WHERE x < ? AND y IN ({})".equals(outC1));

        // C2: %s with sqlite dbType uses IN ({}) instead of ANY(%s)
        String sqlC2 = "SELECT a FROM t WHERE x = %s";
        String outC2 = EqSQLHelper.optimizeQuery(sqlC2, "sqlite");
        System.out.println("SQL C2: " + outC2);
        check(failures, "SQL C2 (dbType routing)", outC2,
              "SELECT a FROM t WHERE x IN ({})".equals(outC2));

        // C3: No auto-injection of GROUP BY when query does not have it
        String sqlC3 = "SELECT count(*) FROM t WHERE x = ?";
        String outC3 = EqSQLHelper.optimizeQuery(sqlC3, "sqlite");
        System.out.println("SQL C3: " + outC3);
        check(failures, "SQL C3 (no auto group by)", outC3,
              "SELECT count(*) FROM t WHERE x IN ({})".equals(outC3));

        // C4: DISTINCT preserved
        String sqlC4 = "SELECT DISTINCT c FROM t WHERE x = ?";
        String outC4 = EqSQLHelper.optimizeQuery(sqlC4, "sqlite");
        System.out.println("SQL C4: " + outC4);
        check(failures, "SQL C4 (DISTINCT)", outC4,
              "SELECT DISTINCT c FROM t WHERE x IN ({})".equals(outC4));

        // C5: Param on LHS (? = x) normalized to x IN ({}) / x = ANY(%s)
        String sqlC5 = "SELECT a FROM t WHERE ? = x";
        String outC5 = EqSQLHelper.optimizeQuery(sqlC5, "postgres");
        System.out.println("SQL C5: " + outC5);
        check(failures, "SQL C5 (param LHS)", outC5,
              "SELECT a FROM t WHERE x = ANY(%s)".equals(outC5));

        if (!failures.isEmpty()) {
            StringBuilder sb = new StringBuilder("OptimizeQueryHarness FAILED (")
                .append(failures.size()).append(" failure(s)):\n");
            for (String f : failures) {
                sb.append("  - ").append(f).append("\n");
            }
            throw new AssertionError(sb.toString());
        }

        System.out.println("ALL HARNESS TESTS PASSED");
    }

    private static void check(List<String> failures, String name, String actual, boolean ok) {
        if (!ok) {
            failures.add(name + " -> got: " + actual);
            System.out.println("  FAIL");
        } else {
            System.out.println("  PASS");
        }
    }
}

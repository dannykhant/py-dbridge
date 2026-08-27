package dbridge.eqsql;

import eqsql.dbridge.analysis.eqsql.expr.node.*;
import eqsql.dbridge.analysis.eqsql.trans.TransDriver;

public class EqSQLHelper {

    public static String optimizeQuery(String sql, String dbType) {
        try {
            // 1. Parse
            Node tree = new SQLQueryParser().parse(sql, dbType);
            if (tree == null) return sql;               // unsupported form

            // 2. Simplify/fold via TransDriver
            tree = TransDriver.applyAllTransRules(tree);

            // 3. Batch rewrite: walk AND/OR tree, replace EqNode(col, ParamNode)
            tree = new BatchingVisitor(dbType).rewrite(tree);

            // 4. Serialize to clean SQL
            return new CleanSQLSerializer().render(tree);
        } catch (Exception e) {
            System.err.println("EqSQLHelper optimization error: " + e);
            return sql;                                  // safe fallback
        }
    }
}

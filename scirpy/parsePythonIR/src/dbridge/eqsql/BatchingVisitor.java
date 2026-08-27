package dbridge.eqsql;

import eqsql.dbridge.analysis.eqsql.expr.node.*;

public class BatchingVisitor {
    private final String dbType;

    public BatchingVisitor(String dbType) {
        this.dbType = dbType;
    }

    public Node rewrite(Node root) {
        if (root == null) return null;

        if (root instanceof GroupByNode || root instanceof ProjectNode || 
            root instanceof SelectNode || root instanceof AndNode || root instanceof OrNode) {
            for (int i = 0; i < root.getNumChildren(); i++) {
                root.setChild(i, rewrite(root.getChild(i)));
            }
            return root;
        }

        if (root instanceof EqNode) {
            EqNode eq = (EqNode) root;
            Node lhs = eq.getChild(0);
            Node rhs = eq.getChild(1);

            // If param is on LHS, swap so it's on RHS
            if (lhs instanceof ParamNode && !(rhs instanceof ParamNode)) {
                Node tmp = lhs;
                lhs = rhs;
                rhs = tmp;
                eq.setChild(0, lhs);
                eq.setChild(1, rhs);
            }

            if (rhs instanceof SQLParamNode) {
                SQLParamNode sp = (SQLParamNode) rhs;
                eq.setChild(1, new BatchParamNode(sp.getParamIndex(), dbType, sp.getNamedParam()));
            } else if (rhs instanceof ParamNode && !(rhs instanceof BatchParamNode)) {
                eq.setChild(1, new BatchParamNode(0, dbType, null));
            }
            return eq;
        }

        return root;
    }
}

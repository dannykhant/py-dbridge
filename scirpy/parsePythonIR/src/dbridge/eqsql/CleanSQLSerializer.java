package dbridge.eqsql;

import eqsql.dbridge.analysis.eqsql.expr.node.*;
import eqsql.dbridge.analysis.eqsql.expr.operator.*;

public class CleanSQLSerializer {
    public String render(Node root) {
        if (root == null) return "";
        
        if (root instanceof ProjectNode) {
            ProjectNode proj = (ProjectNode) root;
            Node source = proj.getChild(0);
            Node cols = proj.getChild(1);
            
            String colStr;
            if (cols instanceof ProjectionListNode) {
                colStr = render(cols);
            } else {
                colStr = render(cols);
            }
            
            String fromStr = render(source);
            String distinctStr = proj.isDistinct() ? "DISTINCT " : "";
            return "SELECT " + distinctStr + colStr + " " + fromStr;
        }
        
        if (root instanceof ProjectionListNode) {
            ProjectionListNode plist = (ProjectionListNode) root;
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < plist.getChildren().length; i++) {
                if (i > 0) sb.append(", ");
                sb.append(render(plist.getChild(i)));
            }
            return sb.toString();
        }
        
        if (root instanceof SelectNode) {
            SelectNode sel = (SelectNode) root;
            String fromStr = render(sel.getChild(0));
            String condStr = render(sel.getChild(1));
            return fromStr + " WHERE " + condStr;
        }
        
        if (root instanceof CartesianProdNode) {
            CartesianProdNode cp = (CartesianProdNode) root;
            StringBuilder sb = new StringBuilder("FROM ");
            for (int i = 0; i < cp.getChildren().length; i++) {
                if (i > 0) sb.append(", ");
                ClassRefOp op = (ClassRefOp) cp.getChild(i).getOperator();
                sb.append(op.getClassName());
            }
            return sb.toString();
        }
        
        if (root instanceof GroupByNode) {
            GroupByNode gb = (GroupByNode) root;
            String sourceStr = render(gb.getChild(0));
            Node colNode = gb.getChild(1);
            String colName = "";
            if (colNode instanceof VarNode) {
                colName = colNode.toString();
            } else if (colNode instanceof FieldRefNode) {
                colName = ((FieldRefOp) colNode.getOperator()).getFieldName();
            }

            return sourceStr + " GROUP BY " + colName;
        }
        
        if (root instanceof EqNode) {
            EqNode eq = (EqNode) root;
            Node lhs = eq.getChild(0);
            Node rhs = eq.getChild(1);
            if (rhs instanceof BatchParamNode) {
                String lhsStr = render(lhs);
                String rhsStr = ((BatchParamNode) rhs).render();
                return lhsStr + " " + rhsStr;
            } else if (lhs instanceof BatchParamNode) {
                String rhsStr = render(rhs);
                String lhsStr = ((BatchParamNode) lhs).render();
                return rhsStr + " " + lhsStr;
            }
            String lhsStr = render(lhs);
            String rhsStr = render(rhs);
            return lhsStr + " = " + rhsStr;
        }
        
        if (root instanceof NotEqNode) {
            NotEqNode neq = (NotEqNode) root;
            return render(neq.getChild(0)) + " <> " + render(neq.getChild(1));
        }
        
        if (root instanceof LtNode) {
            return render(root.getChild(0)) + " < " + render(root.getChild(1));
        }
        
        if (root instanceof GtNode) {
            return render(root.getChild(0)) + " > " + render(root.getChild(1));
        }
        
        if (root instanceof LeNode) {
            return render(root.getChild(0)) + " <= " + render(root.getChild(1));
        }
        
        if (root instanceof GeNode) {
            return render(root.getChild(0)) + " >= " + render(root.getChild(1));
        }
        
        if (root instanceof AndNode) {
            return render(root.getChild(0)) + " AND " + render(root.getChild(1));
        }
        
        if (root instanceof OrNode) {
            return render(root.getChild(0)) + " OR " + render(root.getChild(1));
        }
        
        if (root instanceof VarNode) {
            return root.toString();
        }
        
        if (root instanceof FieldRefNode) {
            return ((FieldRefOp) root.getOperator()).getFieldName();
        }
        
        if (root instanceof StringConstNode) {
            String val = ((StringConstNode) root).getStr();
            return "'" + val + "'";
        }
        
        if (root instanceof IntConstNode) {
            return String.valueOf(((IntConstNode) root).getValue());
        }
        
        if (root instanceof CountStarNode) {
            return "count(*)";
        }
        
        if (root instanceof BatchParamNode) {
            return ((BatchParamNode) root).render();
        }
        
        if (root instanceof SQLParamNode) {
            return ((SQLParamNode) root).render();
        }
        
        if (root instanceof ParamNode) {
            return "?"; // Fallback
        }
        
        return "";
    }
}

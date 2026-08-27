package eqsql.dbridge.analysis.eqsql.expr.node;
import eqsql.dbridge.analysis.eqsql.expr.operator.GeOp;
public class GeNode extends Node {
    public GeNode(Node lhs, Node rhs) { super(new GeOp(), lhs, rhs); }
}

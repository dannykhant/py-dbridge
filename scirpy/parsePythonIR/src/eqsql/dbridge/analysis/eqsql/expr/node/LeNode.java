package eqsql.dbridge.analysis.eqsql.expr.node;
import eqsql.dbridge.analysis.eqsql.expr.operator.LeOp;
public class LeNode extends Node {
    public LeNode(Node lhs, Node rhs) { super(new LeOp(), lhs, rhs); }
}

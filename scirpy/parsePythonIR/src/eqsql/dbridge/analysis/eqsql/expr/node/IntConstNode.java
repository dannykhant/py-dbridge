package eqsql.dbridge.analysis.eqsql.expr.node;
import eqsql.dbridge.analysis.eqsql.expr.operator.IntConstOp;
public class IntConstNode extends LeafNode {
    public IntConstNode(int value) { super(new IntConstOp(value)); }
    public int getValue() { return ((IntConstOp) operator).getValue(); }
}

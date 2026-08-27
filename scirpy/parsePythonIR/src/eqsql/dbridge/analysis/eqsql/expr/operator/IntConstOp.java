package eqsql.dbridge.analysis.eqsql.expr.operator;

public class IntConstOp extends Operator {
    private final int value;

    public IntConstOp(int value) {
        super(String.valueOf(value), OpType.IntConst, 0);
        this.value = value;
    }

    public int getValue() {
        return value;
    }
}

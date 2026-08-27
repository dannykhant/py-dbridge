package dbridge.eqsql;
import eqsql.dbridge.analysis.eqsql.expr.node.LeafNode;
import eqsql.dbridge.analysis.eqsql.expr.operator.ParamOp;

public class BatchParamNode extends LeafNode {
    private final String dbType;
    private final String namedParam; // null for positional (%s / ?)

    public BatchParamNode(int paramNumber, String dbType, String namedParam) {
        super(new ParamOp(paramNumber));
        this.dbType = dbType;
        this.namedParam = namedParam;
    }

    public String render() {
        if ("postgres".equalsIgnoreCase(dbType)) {
            return namedParam != null
                ? "= ANY(%(" + namedParam + ")s)"
                : "= ANY(%s)";
        }
        return "IN ({})";
    }
}

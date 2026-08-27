package dbridge.eqsql;

import eqsql.dbridge.analysis.eqsql.expr.node.ParamNode;

public class SQLParamNode extends ParamNode {
    private final int paramIndex;
    private final String rawPlaceholder;
    private final String namedParam;

    public SQLParamNode(int paramIndex, String rawPlaceholder, String namedParam) {
        super(paramIndex);
        this.paramIndex = paramIndex;
        this.rawPlaceholder = rawPlaceholder;
        this.namedParam = namedParam;
    }

    public int getParamIndex() {
        return paramIndex;
    }

    public String getRawPlaceholder() {
        return rawPlaceholder;
    }

    public String getNamedParam() {
        return namedParam;
    }

    public String render() {
        return rawPlaceholder != null ? rawPlaceholder : "?";
    }

    @Override
    public String toString() {
        return render();
    }
}

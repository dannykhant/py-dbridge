package eqsql.dbridge.analysis.eqsql.expr.node;
import eqsql.dbridge.analysis.eqsql.expr.operator.ProjectionListOp;
public class ProjectionListNode extends Node {
    public ProjectionListNode(Node... cols) {
        super(new ProjectionListOp(cols.length), cols);
    }
}

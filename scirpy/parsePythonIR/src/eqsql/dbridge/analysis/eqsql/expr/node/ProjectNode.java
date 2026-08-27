package eqsql.dbridge.analysis.eqsql.expr.node;

import eqsql.dbridge.analysis.eqsql.expr.operator.ProjectOp;
import eqsql.exceptions.QueryTranslationException;

/**
 * Created by ek on 17/10/16.
 */
public class ProjectNode extends Node implements HQLTranslatable, SQLTranslatable{
    private boolean distinct = false;

    public ProjectNode(Node fromNode, Node projectionNode) {
        this(fromNode, projectionNode, false);
    }

    public ProjectNode(Node fromNode, Node projectionNode, boolean distinct) {
        super(new ProjectOp(), fromNode, projectionNode);
        this.distinct = distinct;
    }

    public boolean isDistinct() {
        return distinct;
    }

    public void setDistinct(boolean distinct) {
        this.distinct = distinct;
    }

    @Override
    public String toHibQuery() throws QueryTranslationException {
        String relationHQL = ((HQLTranslatable) children[0]).toHibQuery();
        String projElHQL = ((HQLTranslatable) children[1]).toHibQuery();

        return "(select " + projElHQL + " " + relationHQL + ")";
        /* Note: "from" keyword is already part of relationHQL */
    }

    @Override
    public String toSQLQuery() throws QueryTranslationException {
        String relationHQL = ((SQLTranslatable) children[0]).toSQLQuery();
        String projElHQL = ((SQLTranslatable) children[1]).toSQLQuery();

        return "(select " + projElHQL + " " + relationHQL + ")";
        /* Note: "from" keyword is already part of relationHQL */
    }
}

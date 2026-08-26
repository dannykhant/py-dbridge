package parse.ops;

import ast.ExprAST;
import ir.IExpr;
import ir.expr.Call;
import ir.expr.ListComp;
import ir.expr.Name;
import org.json.simple.JSONArray;
import org.json.simple.JSONObject;
import parse.*;

public class OpParser {
    JSONObject opObj;

    public OpParser(JSONObject opObj) {
        this.opObj = opObj;
    }
    public OpParser() {
    }

    public IExpr parseOp() {
        return parseOp(opObj);
    }

    public IExpr parseOp(JSONObject opObj) {
        IExpr expr = null;
        String opType = opObj.get("ast_type").toString();

        switch (opType) {
            case "BoolOp":
                BoolOpParser boolOpParser=new BoolOpParser();
                expr=boolOpParser.parseBoolOp(opObj);
                break;
            case "Compare":
                CompareParser compareParser=new CompareParser(opObj);
                expr=compareParser.getCompare();
                break;
            case "BinOp":
                BinOpParser binOpParser=new BinOpParser(opObj);
                expr=binOpParser.getBinOp();
                break;
            case "Constant":
                GenericExpressionParser gepc=new GenericExpressionParser();
                expr=gepc.getConstant(opObj);
                break;
            case "Name":
                GenericExpressionParser gepn=new GenericExpressionParser();
                expr=gepn.getName(opObj);
                break;
            case "UnaryOp":
                UnaryOpParser uop=new UnaryOpParser(opObj);
                expr=uop.getUnaryOp();
                break;
            case "Attribute":
                AttributeParser ap=new AttributeParser();
                expr=ap.parseAttribute(opObj);
                break;
            case "Subscript":
                SubscriptParser sp=new SubscriptParser();
                expr=sp.parseSubscript(opObj);
                break;
            case "Call":
                GetCall getCall=new GetCall();
                Call call=getCall.GetFunctionalCall(opObj);
                call.setAst_type(ExprAST.Call);
                expr=call;
                break;
            default:
                System.out.println(opType +" not implemented in OpParser");
                throw new RuntimeException(opType + " not implemented in OpParser");
        }
        return expr;
    }
}

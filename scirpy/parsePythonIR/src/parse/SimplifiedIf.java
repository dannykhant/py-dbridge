package parse;

import ir.IExpr;
import ir.Stmt.IfStmt;
import ir.Stmt.IfStmtPy;
import ir.Stmt.NopStmt;
import ir.expr.*;
import parse.ops.BoolOpParser;
import soot.PatchingChain;
import soot.Unit;
import soot.jimple.Jimple;
import soot.util.Chain;
import soot.util.HashChain;
import ir.DataType.IntType;

import java.util.ArrayList;
import java.util.List;
import ir.internalast.Value;

public class SimplifiedIf {

    public PatchingChain<Unit> getSimplifiedIf(IfStmtPy ifStmtPy, boolean whileBool, Chain locals){
        PatchingChain<Unit> extendedIfList=new PatchingChain<Unit>(new HashChain<Unit>());
        IExpr test= ifStmtPy.getTest();
        //TODO createSimpleConditions and Add statements for them in extendedIfList
        IExpr condition=createSimpleConditions(test, extendedIfList);
        NopStmt nop= new ir.Stmt.NopStmt();//Jimple.v().newNopStmt();
        IfStmt ifStmt=new IfStmt(condition,nop);
        ifStmt.copyIf(ifStmtPy);
        ifStmt.setPyStmt(ifStmtPy);
        ifStmt.setLineno(ifStmtPy.getLineno());
        //extendedIfList.add(ifStmt);
        IfStmtHelper ifStmtHelper=new IfStmtHelper();
        if(!whileBool)
            ifStmtHelper.addDetailedStmtsIf(extendedIfList,ifStmt,locals);
        if(whileBool) {
            ifStmtPy.setWhile(true);
            //Modified on Apr 29, 2024
//            ifStmtHelper.addDetailedStmtsWhile(extendedIfList, ifStmt, locals);
            ifStmtHelper.addDetailedStmtsIf(extendedIfList,ifStmt,locals);

        }
        return extendedIfList;

    }

    private IExpr createSimpleConditions(IExpr test, PatchingChain<Unit> extendedIfList) {
        if (test instanceof Compare) {
            return (Compare) test;
        }
        else if (test instanceof BoolOp) {
            BoolOp b = (BoolOp) test;
            for (Object v : b.getValues()) {
                if (v instanceof Compare) {
                    return (IExpr) v;
                }
            }
            Compare cmp = new Compare();
            if (!b.getValues().isEmpty() && b.getValues().get(0) instanceof IExpr) {
                cmp.setLeft((IExpr) b.getValues().get(0));
            }
            cmp.getOps().add(ir.expr.OpsType.IsNot);
            cmp.getComparators().add(new Num(-1, -1, new IntType(0, "0")));
            return cmp;
        }
        else if (test instanceof soot.jimple.ConditionExpr) {
            return test;
        }
        else {
            Compare cmp = new Compare();
            if (test != null) {
                cmp.setLeft(test);
            }
            cmp.getOps().add(ir.expr.OpsType.IsNot);
            cmp.getComparators().add(new Num(-1, -1, new IntType(0, "0")));
            return cmp;
        }
    }

    //Should not be used anymore..changed implementation
/*
    private List<OpsType> reverseOps(Compare originalTest) {
        List<OpsType> opsTypes=new ArrayList<>();
        for(OpsType opsType:originalTest.getOps()){
        opsTypes.add(ReverseOp.getReverseOp(opsType));
    }
    return opsTypes;
}
*/

}

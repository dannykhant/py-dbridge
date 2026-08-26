package ir;

import soot.Local;
import soot.PatchingChain;
import soot.Unit;
import soot.jimple.StmtBody;
import soot.util.Chain;
import soot.util.HashChain;

import java.util.ArrayList;
import java.util.List;

public class JPBody extends StmtBody {

    public JPBody(JPMethod method, PatchingChain<Unit> unitChain,
                  Chain<Local> localChain) {
        super(method);
        this.unitChain = unitChain;
        this.localChain = localChain;
    }

    public JPBody() {
        super();
    }

    @Override
    public Object clone() {
        PatchingChain<Unit> unitChainClone = new PatchingChain<Unit>(new HashChain<Unit>());
        Chain<Local> localsClone = new HashChain<Local>();
        for (Unit unit : unitChain) {
            unitChainClone.add((Unit) unit.clone());
        }
        List<Local> parameterTypes = new ArrayList<>();
        JPMethod jpMethod = new JPMethod("Module", parameterTypes, null);
        JPBody jpBody = new JPBody(jpMethod, unitChainClone, localsClone);
        jpBody.getMethod().setActiveBody(jpBody);
        return this;
    }
}

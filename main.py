import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any
from datetime import datetime, timezone

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    prompt: str = Field(..., min_length=15, description="Free-form description of the decision")


class Recommendation(BaseModel):
    id: str
    title: str
    summary: str
    bullets: List[str]
    badge: Literal["Conservadora", "Balance", "Riesgo alto", "Exploratoria", "Precisa", "Eficiente"] = "Balance"
    recommended: bool = False


class AnalyzeResponse(BaseModel):
    robot_message: str
    status: Literal["analyzing", "ready"] = "ready"
    recommendations: List[Recommendation]
    decision_id: Optional[str] = None
    metadata: Dict[str, Any] = {}


@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    
    try:
        # Try to import database module
        from database import db
        
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            
            # Try to list collections to verify connectivity
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]  # Show first 10 collections
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
            
    except ImportError:
        response["database"] = "❌ Database module not found (run enable-database first)"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    
    # Check environment variables
    import os
    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    
    return response


def _generate_recommendations(prompt: str) -> List[Recommendation]:
    """
    Very lightweight heuristic to shape 3 routes of decision based on user intent.
    This is NOT a product catalog; it focuses on trade-offs and priorities.
    """
    text = prompt.lower()

    # Simple signals
    budget = None
    import re
    m = re.search(r"(\d{2,3})\s?(k|mil|000|k\s?mxn|mxn)", text)
    if m:
        try:
            num = int(m.group(1))
            budget = num * (1000 if m.group(2) in ["k", "mil", "k mxn", "mxn"] else 1)
        except Exception:
            budget = None

    priorities = []
    if any(k in text for k in ["peso", "liger", "portátil", "portatil"]):
        priorities.append("portabilidad")
    if any(k in text for k in ["render", "3d", "lumion", "blender", "revit", "potencia", "gpu"]):
        priorities.append("rendimiento")
    if any(k in text for k in ["durabil", "garant", "soporte", "confi"]):
        priorities.append("confianza")
    if any(k in text for k in ["silenc", "ruido"]):
        priorities.append("ruido")

    # Build routes
    recs: List[Recommendation] = []

    recs.append(Recommendation(
        id="route_balance",
        title="Ruta A – Equilibrio rendimiento / precio",
        summary="Balancea potencia suficiente con cuidado del presupuesto.",
        bullets=[
            "Prioriza GPU y RAM sobre detalles cosméticos.",
            "Mantiene el presupuesto bajo control" + (f" (≤ {budget:,} MXN)" if budget else "."),
            "Acepta un peso medio para no sacrificar demasiada potencia.",
            "Propone marcas con buen soporte técnico para minimizar riesgos.",
        ],
        badge="Balance",
        recommended=True
    ))

    recs.append(Recommendation(
        id="route_power",
        title="Ruta B – Máxima potencia para cargas pesadas",
        summary="Prioriza rendimiento sostenido para 3D y render, asumiendo trade-offs.",
        bullets=[
            "Maximiza GPU/CPU y memoria para proyectos exigentes.",
            "Puede exceder un poco el presupuesto si el beneficio es claro.",
            "Acepta mayor peso y menor batería para ganar velocidad.",
            "Sugiere sistemas de enfriamiento más robustos (algo más de ruido).",
        ],
        badge="Riesgo alto",
        recommended=False
    ))

    recs.append(Recommendation(
        id="route_portability",
        title="Ruta C – Ultra ligera, consciente del sacrificio",
        summary="Optimiza portabilidad y ergonomía, sacrificando potencia tope.",
        bullets=[
            "Elige chasis delgados y materiales ligeros.",
            "Rinde bien en tareas de diseño medio; renderizados más lentos.",
            "Se enfoca en autonomía y menor ruido cuando es posible.",
            "Se asegura de que el peso total sea cómodo para transporte diario.",
        ],
        badge="Conservadora",
        recommended=False
    ))

    # Tweak ordering based on detected priorities
    if "portabilidad" in priorities:
        recs[0].recommended = False
        recs[2].recommended = True

    if "rendimiento" in priorities:
        recs[0].recommended = False
        recs[1].recommended = True

    return recs


@app.post("/api/decision/analyze", response_model=AnalyzeResponse)
def analyze_decision(req: AnalyzeRequest):
    if not req.prompt or len(req.prompt.strip()) < 15:
        raise HTTPException(status_code=400, detail="La descripción es muy corta. Agrega propósito, presupuesto y prioridades.")

    # Create recommendations
    recs = _generate_recommendations(req.prompt)

    # Compose robot message
    robot_message = (
        "Entiendo tu objetivo y voy a priorizar lo que más te importa. "
        "Aquí tienes 2–3 rutas de decisión con sus trade-offs. "
        "¿Prefieres optimizar portabilidad, rendimiento puro o un balance claro?"
    )

    decision_id = None
    metadata = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "length": len(req.prompt),
    }

    # Try to persist the decision route in the Decision Vault (MongoDB)
    try:
        from database import create_document
        payload = {
            "prompt": req.prompt,
            "robot_message": robot_message,
            "recommendations": [r.model_dump() for r in recs],
            "metadata": metadata,
            "type": "decision_route"
        }
        decision_id = create_document("decisionroute", payload)
    except Exception:
        # Database is optional for the prototype; continue without failing
        decision_id = None

    return AnalyzeResponse(
        robot_message=robot_message,
        status="ready",
        recommendations=recs,
        decision_id=decision_id,
        metadata=metadata,
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

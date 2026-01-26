from datetime import datetime
import csv
import io

from fastapi import FastAPI, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy.orm import Session
from sqlalchemy import or_

from database import engine, get_db
from models import Base, Card, PriceHistory


# DB-Tabellen automatisch anlegen (MVP)
Base.metadata.create_all(bind=engine)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def redirect_home(error: str | None = None):
    # Redirect zur Startseite, optional mit Fehlercode für die UI.
    url = "/" if not error else f"/?error={error}"
    return RedirectResponse(url=url, status_code=303)


def is_duplicate(db: Session, card_code: str, name: str, set_name: str) -> bool:
    # Duplikate verhindern: gleicher card_code oder gleiche Kombination (name + set_name).
    if db.query(Card).filter(Card.card_code == card_code).first():
        return True
    if db.query(Card).filter(Card.name == name, Card.set_name == set_name).first():
        return True
    return False


def apply_search_and_sort(query, q: str, sort: str):
    
    # Wendet Suche (q) und Sortierung (sort) auf die Karten-Query an.
    q = q.strip() if q else ""
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Card.name.ilike(like), Card.card_code.ilike(like)))

    if sort == "price_desc":
        return query.order_by(Card.price.desc())
    if sort == "price_asc":
        return query.order_by(Card.price.asc())
    if sort == "name_asc":
        return query.order_by(Card.name.asc())

    return query.order_by(Card.id.desc())


def load_histories_and_trends(db: Session, cards, limit: int = 5):
    # Lädt Preis-Historie pro Karte und berechnet Trend (up/down/same/none).
    histories = {}
    trends = {}

    for card in cards:
        h = (
            db.query(PriceHistory)
            .filter(PriceHistory.card_id == card.id)
            .order_by(PriceHistory.created_at.desc())
            .limit(limit)
            .all()
        )
        histories[card.id] = h

        if len(h) >= 2:
            if h[0].price > h[1].price:
                trends[card.id] = "up"
            elif h[0].price < h[1].price:
                trends[card.id] = "down"
            else:
                trends[card.id] = "same"
        else:
            trends[card.id] = "none"

    return histories, trends


def compute_dashboard(cards, histories):
    # Berechnet Kennzahlen fürs Dashboard (Anzahl, Gesamtwert, Top Gainer/Loser).
    card_count = len(cards)
    total_value = sum((c.price or 0) for c in cards)

    top_gainer = None
    top_loser = None
    best_diff = None
    worst_diff = None

    for card in cards:
        h = histories.get(card.id, [])
        if len(h) >= 2:
            diff = h[0].price - h[1].price

            if best_diff is None or diff > best_diff:
                best_diff = diff
                top_gainer = {"card": card, "diff": diff}

            if worst_diff is None or diff < worst_diff:
                worst_diff = diff
                top_loser = {"card": card, "diff": diff}

    return card_count, total_value, top_gainer, top_loser


@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    db: Session = Depends(get_db),
    sort: str = "",
    q: str = "",
    error: str = "",
):
    query = apply_search_and_sort(db.query(Card), q, sort)
    cards = query.all()

    histories, trends = load_histories_and_trends(db, cards)
    card_count, total_value, top_gainer, top_loser = compute_dashboard(cards, histories)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "cards": cards,
            "histories": histories,
            "trends": trends,
            "card_count": card_count,
            "total_value": total_value,
            "top_gainer": top_gainer,
            "top_loser": top_loser,
            "error": error,
            "q": q,
            "sort": sort,
        },
    )


@app.post("/add-card")
def add_card(
    request: Request,
    name: str = Form(...),
    price: float = Form(...),
    card_code: str = Form(...),
    db: Session = Depends(get_db),
):
    card_code = card_code.strip().upper()
    name = name.strip()

    # Set/Edition wird bewusst aus dem card_code abgeleitet (z.B. OP13-118 -> OP13)
    if "-" not in card_code:
        return redirect_home("codeformat")

    set_name = card_code.split("-")[0]
    image_url = None  # MVP: Bilder kommen aus /static/cards/<card_code>.(png/jpg)

    if price < 0:
        return redirect_home("price")

    if len(name) == 0 or len(card_code) == 0:
        return redirect_home("empty")

    if len(name) > 60:
        return redirect_home("toolong")

    if is_duplicate(db, card_code, name, set_name):
        return redirect_home("duplicate")

    card = Card(
        card_code=card_code,
        name=name,
        set_name=set_name,
        price=price,
        image_url=image_url,
    )
    db.add(card)
    db.flush()         
    db.add(PriceHistory(card_id=card.id, price=price))
    db.commit()


    return redirect_home()


@app.post("/update-price/{card_id}")
def update_price(card_id: int, new_price: float = Form(...), db: Session = Depends(get_db)):
    if new_price < 0:
        return redirect_home("price")

    card = db.query(Card).filter(Card.id == card_id).first()
    if not card:
        return redirect_home()

    card.price = new_price
    db.add(PriceHistory(card_id=card.id, price=new_price))
    db.commit()

    return redirect_home()


@app.post("/delete-card/{card_id}")
def delete_card(card_id: int, db: Session = Depends(get_db)):
    # Beim Löschen einer Karte werden ihre Historien-Einträge mit entfernt (MVP sauber halten)
    db.query(PriceHistory).filter(PriceHistory.card_id == card_id).delete()

    card = db.query(Card).filter(Card.id == card_id).first()
    if card:
        db.delete(card)

    db.commit()
    return redirect_home()


@app.get("/export-csv")
def export_csv(db: Session = Depends(get_db)):
    # Exportiert die aktuelle Sammlung als CSV
    cards = db.query(Card).order_by(Card.id.asc()).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")

    writer.writerow(["id", "card_code", "name", "edition", "price"])
    for c in cards:
        writer.writerow([c.id, c.card_code, c.name, c.set_name, f"{c.price:.2f}"])

    buffer.seek(0)
    filename = f"tcg_export_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.csv"

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

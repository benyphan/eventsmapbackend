from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas, auth
from app.routers.notifications import send_notification

router = APIRouter(prefix="/shop", tags=["shop"])


def _owned_decorations(db: Session, user_id: str) -> List[str]:
    rows = (
        db.query(models.Purchase)
        .join(models.ShopItem, models.Purchase.item_id == models.ShopItem.id)
        .filter(
            models.Purchase.user_id == user_id,
            models.ShopItem.item_type == "decoration",
        )
        .all()
    )
    return [r.item_id for r in rows]


def _gifts_received(db: Session, user_id: str) -> List[schemas.GiftOut]:
    rows = (
        db.query(models.Gift)
        .join(models.ShopItem, models.Gift.item_id == models.ShopItem.id)
        .filter(models.Gift.to_user_id == user_id)
        .order_by(models.Gift.created_at.desc())
        .all()
    )
    return [
        schemas.GiftOut(
            id=g.id,
            from_user_id=g.from_user_id,
            from_user_name=g.from_user.name if g.from_user else None,
            to_user_id=g.to_user_id,
            item_id=g.item_id,
            item_name=g.item.name if g.item else None,
            item_emoji=g.item.emoji if g.item else None,
            message=g.message,
            created_at=g.created_at,
        )
        for g in rows
    ]


@router.get("", response_model=schemas.ShopOut)
def get_shop(
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    items = (
        db.query(models.ShopItem)
        .filter(models.ShopItem.is_active.is_(True))
        .order_by(models.ShopItem.price.asc())
        .all()
    )
    return schemas.ShopOut(
        credits=current_user.credits or 0,
        active_decoration=current_user.active_decoration,
        owned_decorations=_owned_decorations(db, current_user.id),
        items=[
            schemas.ShopItemOut.model_validate(i)
            for i in items
        ],
        gifts_received=_gifts_received(db, current_user.id),
    )


@router.post("/buy/{item_id}", response_model=schemas.PurchaseOut)
def buy_item(
    item_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(models.ShopItem).filter(models.ShopItem.id == item_id).first()
    if not item or not item.is_active:
        raise HTTPException(status_code=404, detail="Предмет не найден")
    if item.item_type != "decoration":
        raise HTTPException(status_code=400, detail="Подарки покупаются для других пользователей")

    if (current_user.credits or 0) < item.price:
        raise HTTPException(status_code=400, detail="Недостаточно кредитов")

    already = _owned_decorations(db, current_user.id)
    if item.id in already:
        raise HTTPException(status_code=400, detail="Украшение уже куплено")

    current_user.credits = (current_user.credits or 0) - item.price
    db.add(models.Purchase(user_id=current_user.id, item_id=item.id))
    current_user.active_decoration = item.id
    db.commit()
    db.refresh(current_user)
    return schemas.PurchaseOut(
        credits=current_user.credits or 0,
        active_decoration=current_user.active_decoration,
    )


@router.post("/gift/{item_id}", response_model=schemas.PurchaseOut)
def gift_item(
    item_id: str,
    payload: schemas.GiftSend,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(models.ShopItem).filter(models.ShopItem.id == item_id).first()
    if not item or not item.is_active:
        raise HTTPException(status_code=404, detail="Предмет не найден")
    if item.item_type != "gift":
        raise HTTPException(status_code=400, detail="Это украшение для профиля, а не подарок")

    if payload.to_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя подарить самому себе")

    recipient = (
        db.query(models.User)
        .filter(models.User.id == payload.to_user_id)
        .first()
    )
    if not recipient:
        raise HTTPException(status_code=404, detail="Получатель не найден")

    if (current_user.credits or 0) < item.price:
        raise HTTPException(status_code=400, detail="Недостаточно кредитов")

    current_user.credits = (current_user.credits or 0) - item.price
    db.add(models.Gift(
        from_user_id=current_user.id,
        to_user_id=recipient.id,
        item_id=item.id,
        message=payload.message,
    ))
    db.commit()
    db.refresh(current_user)

    send_notification(
        db,
        recipient.id,
        "Подарок!",
        f"{current_user.name} подарил(а) тебе «{item.name}» {item.emoji or ''}",
    )
    db.commit()
    return schemas.PurchaseOut(
        credits=current_user.credits or 0,
        active_decoration=current_user.active_decoration,
    )


@router.post("/equip/{item_id}", response_model=schemas.PurchaseOut)
def equip_item(
    item_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    owned = _owned_decorations(db, current_user.id)
    if item_id not in owned:
        raise HTTPException(status_code=400, detail="Украшение не куплено")
    current_user.active_decoration = item_id
    db.commit()
    db.refresh(current_user)
    return schemas.PurchaseOut(
        credits=current_user.credits or 0,
        active_decoration=current_user.active_decoration,
    )

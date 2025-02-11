from fastapi import HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.schemas.car import CarModel, CarUpdate
from src.entity.models import Car, User, user_car_association, History


class CarRepository:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def add_car(self, car_data: CarModel):
        new_car = Car(**car_data.dict(exclude={'user_ids'}))

        # Checking whether the new license plate already exists in the database
        existing_car = await self.db.execute(select(Car).filter(Car.plate == car_data.plate))
        existing_car = existing_car.scalars().first()
        if existing_car:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f'Car with plate {car_data.plate} already exists')

        self.db.add(new_car)

        # Association of the car with users
        for user_id in car_data.user_ids:
            user = await self.db.get(User, user_id)
            if not user:
                await self.db.rollback()
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User with id {user_id} not found")
            new_car.users.append(user)

        await self.db.commit()
        await self.db.refresh(new_car)
        new_car.user_ids = car_data.user_ids
        return new_car

    async def get_car_by_plate(self, plate: str):
        result = await self.db.execute(select(Car).options(selectinload(Car.users)).where(Car.plate == plate))
        car = result.scalars().first()
        if car:
            car.user_ids = [user.id for user in car.users]
        return car

    async def get_all_cars(self):
        result = await self.db.execute(select(Car).options(selectinload(Car.users)))
        cars = result.scalars().unique().all()
        if cars:
            for car in cars:
                car.user_ids = [user.id for user in car.users]
        return cars

    async def get_cars_currently_parked(self):
        result = await self.db.execute(
            select(Car).join(History, Car.id == History.car_id)
            .where(History.entry_time.isnot(None))
            .where(History.exit_time.is_(None))
        )
        cars = result.scalars().unique().all()
        if cars:
            for car in cars:
                car.user_ids = [user.id for user in car.users]
        return cars

    async def get_cars_by_user(self, user_id: int):
        user_exists = await self.db.scalar(select(User.id).where(User.id == user_id))
        if not user_exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        result = await self.db.execute(
            select(Car).options(selectinload(Car.users)).join(Car.users).where(User.id == user_id)
        )
        cars = result.scalars().unique().all()
        if cars:
            for car in cars:
                car.user_ids = [user.id for user in car.users]
        return cars

    async def get_users_by_car_plate(self, plate: str):
        result = await self.db.execute(select(User).join(Car.users).where(Car.plate == plate))
        users = result.scalars().unique().all()
        return users

    async def update_car(self, plate: str, car_update: CarUpdate):
        statement = select(Car).where(Car.plate == plate)
        result = await self.db.execute(statement)
        car = result.scalars().first()
        if not car:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Car not found")

        if car_update.plate and car_update.plate != plate:
            existing_car = await self.db.execute(select(Car).filter(Car.plate == car_update.plate))
            existing_car = existing_car.scalars().first()
            if existing_car:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                    detail=f"Car with plate {car_update.plate} already exists")

        if car_update.user_ids is not None:
            car.users.clear()  # Clearing the user list
            for user_id in car_update.user_ids:
                user = await self.db.get(User, user_id)
                if not user:
                    await self.db.rollback()
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                        detail=f"User with id {user_id} not found")
                car.users.append(user)

        for var, value in car_update.dict(exclude_unset=True, exclude={'user_ids'}).items():
            setattr(car, var, value)

        await self.db.commit()
        await self.db.refresh(car)
        car.user_ids = [user.id for user in car.users]  # We write user IDs in the list
        return car

    async def delete_car(self, plate: str):
        car = await self.db.execute(select(Car).where(Car.plate == plate))
        car = car.scalars().first()

        # Removal of associations with users
        await self.db.execute(delete(user_car_association).where(user_car_association.c.car_id == car.id))

        await self.db.delete(car)
        await self.db.commit()
        return

    async def ban_car(self, plate: str):
        statement = select(Car).where(Car.plate == plate)
        result = await self.db.execute(statement)
        car = result.scalars().first()
        if car is None:
            return None
        car.ban = True
        await self.db.commit()
        return True

    async def check_car_exists(self, plate: str):
        result = await self.db.execute(select(Car).where(Car.plate == plate))
        return result.scalars().first() is not None

    async def get_user_id_by_car_id(self, car_id: int):
        result = await self.db.execute(select(User.id).join(User.cars).where(Car.id == car_id))
        user = result.scalar_one_or_none()
        if user is None:
            return None
        return user

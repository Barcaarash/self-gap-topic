import redis.asyncio
from .enums import Status



cache  = redis.asyncio.Redis(host='redis', decode_responses=True)

async def get_user_status(user_id: int):
    status = await cache.get(f'user_status:{user_id}')
    if status:
        return Status(status)
    
    else:
        return Status.NULL

async def set_user_status(user_id: int, status: Status):
    await cache.set(f'user_status:{user_id}', status.value)


    
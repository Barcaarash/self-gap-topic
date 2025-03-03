import time
import os
import config
import peewee
from datetime import datetime

# Create directory for SQLite database
os.makedirs('.app-data/sqlite', exist_ok=True)

# Use SQLite database instead of MySQL
database = peewee.SqliteDatabase('.app-data/sqlite/support-bot.db')

class BaseModel(peewee.Model):
    class Meta:
        database = database

class Users(BaseModel):
    id = peewee.AutoField()
    user_id = peewee.BigIntegerField(index=True)
    topic_id = peewee.IntegerField(index=True, null=True)
    registration_date = peewee.DateTimeField(default=datetime.now)


class Notes(BaseModel):
    id = peewee.AutoField()
    user_id = peewee.BigIntegerField(index=True)
    message = peewee.TextField()
    last_used_date = peewee.DateTimeField(default=datetime.now)


class Messages(BaseModel):
    id = peewee.AutoField()
    user = peewee.ForeignKeyField(Users,
                                  backref='messages',
                                  on_delete='CASCADE')
    user_message_id = peewee.IntegerField(index=True)
    topic_message_id = peewee.IntegerField(index=True)


for _ in range(10):
    try:
        database.connect()

    except BaseException:
        time.sleep(1)

    else:
        database.create_tables([Users, Notes, Messages])
        break

else:
    exit('Unable to connect to SQLite database')

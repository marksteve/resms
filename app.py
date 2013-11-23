from flask import (
  Flask,
  render_template,
  request,
  session,
  redirect,
  url_for,
  abort,
)
from flask_redisconfig import RedisConfig
from simpleflake import simpleflake
import redis
import sys


fl = Flask(__name__)
conf = RedisConfig('resmsconfig')
conf.init_app(fl)
db = redis.StrictRedis()


def key(*a):
  return ":".join(map(str, a))


def create_app():
  app_id = simpleflake()
  db.hmset(app_id, dict(
    id=app_id,
    email=request.form["email"].strip().lower(),
    shortcode=int(request.form["shortcode"].strip()),
  ))
  return app_id


def get_app(app_id):
  return db.hgetall(app_id)


def get_users(app_id):
  return db.smembers(key("users", app_id))


@fl.route("/")
def index():
  return render_template("index.html")


@fl.route("/register", methods=["POST"])
def register():
  session['app_id'] = create_app()
  return redirect(url_for("dashboard"))


@fl.route("/dashboard", methods=["GET", "POST"])
def dashboard():
  if "app_id" not in session:
    abort(401)
  app_id = session["app_id"]
  app = get_app(app_id)
  users = get_users(app_id)
  return render_template(
    "dashboard.html",
    app=app,
    users=users,
  )


@fl.route("/subscribe/<app_id>", methods=["GET"])
def subscribe(app_id):
  u = request.args["subscriber_number"]
  k = key("users", app_id, u)
  if not db.exists(k):
    abort(400)
  db.set(k, request.args["access_token"])
  db.sadd(key("users", app_id), u)
  return ""


@fl.route("/receive/<app_id>", methods=["POST"])
def receive(app_id):
  return ""


def main():
  fl.run(host="0.0.0.0", debug=True)


if __name__ == '__main__':
  if len(sys.argv) > 1:
    if sys.argv[1] == 'config':
      conf.cli()
    exit()
  main()


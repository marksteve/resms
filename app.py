from functools import wraps
from flask import (
  Flask,
  abort,
  flash,
  g,
  redirect,
  render_template,
  request,
  session,
  url_for,
)
from flask_redisconfig import RedisConfig
from simpleflake import simpleflake
import json
import redis
import requests
import sys


fl = Flask(__name__)
conf = RedisConfig('resmsconfig')
conf.init_app(fl)
db = redis.StrictRedis()


def key(*a):
  return ":".join(map(str, a))


def create_app():
  app_id = simpleflake()
  # Store app
  db.hmset(key("apps", app_id), dict(
    id=app_id,
    email=request.form["email"].strip().lower(),
    shortcode=int(request.form["shortcode"].strip()),
  ))
  return app_id


def get_app(app_id):
  return db.hgetall(key("apps", app_id))


def get_users(app_id):
  return db.smembers(key("users", app_id))


def get_user_token(app_id, user_id):
  return db.get(key("users", app_id, user_id))


def create_survey(app_id):
  survey_id = simpleflake()
  question = request.form["question"].strip()
  choices = map(lambda s: s.strip().upper(), request.form["choices"].strip().split("\n"))
  # Store survey
  db.hmset(key("surveys", app_id, survey_id), dict(
    id=survey_id,
    question=question,
  )),
  # Add choices
  db.sadd(key("choices", app_id, survey_id), *choices)
  # Set current survey
  db.set(key("curr_survey", app_id), survey_id)
  return survey_id


def get_choices(app_id, survey_id):
  return db.smembers(key("choices", app_id, survey_id))


def get_survey(app_id, survey_id):
  survey = db.hgetall(key("surveys", app_id, survey_id))
  if survey:
    choices = get_choices(app_id, survey_id)
    responses = dict()
    if choices:
      total = 0
      for choice in choices:
        value = int(db.get(key("responses", app_id, survey_id, choice)) or 0)
        if value > 0:
          responses[choice] = value
          total += value
      if total > 0:
        for choice, value in responses.items():
          responses[choice] = (value, int(100.0 * value / total))
    survey.update(
      total=total,
      responses=reversed(sorted(responses.items(), key=lambda x: x[1][1])),
    )
  return survey


def get_curr_survey(app_id):
  survey_id = db.get(key("curr_survey", app_id))
  if survey_id:
    return get_survey(app_id, survey_id)


def sess_required(f):
  @wraps(f)
  def decorated(*args, **kwargs):
    if "app_id" not in session:
      abort(401)
    g.app_id = session["app_id"]
    return f(*args, **kwargs)
  return decorated


@fl.route("/")
def index():
  return render_template("index.html")


@fl.route("/register", methods=["POST"])
def register():
  session['app_id'] = create_app()
  flash(
    "You're almost done! Just update your app's Notify and "
    "Redirect URIs with the ones below and you're ready to go.",
    "info",
  )
  return redirect(url_for("dashboard"))


@fl.route("/dashboard", methods=["GET", "POST"])
@sess_required
def dashboard():
  app = get_app(g.app_id)
  users = get_users(g.app_id)
  survey = get_curr_survey(g.app_id)
  return render_template(
    "dashboard.html",
    app=app,
    users=users,
    survey=survey,
  )


@fl.route("/dashboard/send", methods=["POST"])
@sess_required
def dashboard_send():
  app = get_app(g.app_id)
  survey_id = create_survey(g.app_id)
  survey = get_survey(g.app_id, survey_id)
  users = get_users(g.app_id)
  sender = str(app["shortcode"])[-4:]
  message = "%s\nREPLY WITH %s" % (
    survey["question"],
    "/".join(get_choices(g.app_id, survey_id)),
  )
  if users:
    for user in users:
      access_token = get_user_token(g.app_id, user)
      params = dict(access_token=access_token)
      payload = json.dumps(dict(
          outboundSMSMessageRequest=dict(
          clientCorrelator=simpleflake(),
          senderAddress="tel:%s" % sender,
          outboundSMSTextMessage=dict(
            message=message,
          ),
          address=["tel:+63%s" % user],
        ),
      ))
      # TODO: Check response
      requests.post(
        "http://devapi.globelabs.com.ph/smsmessaging/v1/outbound/%s/requests" % sender,
        headers={"Content-Type": "application/json"},
        params=params,
        data=payload,
      )
    flash("Sent survey to %d users" % len(users), "info")
  else:
    flash("No users subscribed yet", "error")
  return redirect(url_for("dashboard"))


@fl.route("/subscribe/<app_id>", methods=["GET"])
def subscribe(app_id):
  u = request.args["subscriber_number"]
  k = key("users", app_id, u)
  # Set user access token
  db.set(k, request.args["access_token"])
  # Add to app's users list
  db.sadd(key("users", app_id), u)
  return ""


@fl.route("/receive/<app_id>", methods=["POST"])
def receive(app_id):
  survey = get_curr_survey(app_id)
  choices = get_choices(app_id, survey["id"])
  for m in request.json["inboundSMSMessageList"]["inboundSMSMessage"]:
    choice = m["message"].strip().upper()
    if choice not in choices:
      # FIXME: Send an sms error message
      abort(400)
    # TODO: Check if user
    # FIXME: Don't allow dupe responses
    db.incr(key("responses", app_id, survey["id"], choice))
    break
  return ""


def main():
  fl.run(host="0.0.0.0", debug=True)


if __name__ == '__main__':
  if len(sys.argv) > 1:
    if sys.argv[1] == 'config':
      conf.cli()
    exit()
  main()


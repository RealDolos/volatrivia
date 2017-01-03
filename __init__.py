"""
The MIT License (MIT)
Copyright © 2017 RealDolos

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the “Software”), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""
#pylint: disable=missing-docstring,broad-except
import html
import logging
import random
import re

from collections import namedtuple, Counter
from contextlib import suppress
from difflib import SequenceMatcher
from enum import Enum
from time import time

from volaparrot.commands import PulseCommand
from volaparrot.utils import requests


LOGGER = logging.getLogger(__name__)


def unesc(string):
    return html.unescape(string).strip()


class Question(namedtuple("Question", "id, question, answer")):
    ratio = 0.87
    r_cleanup = re.compile(r"\s+|[\r\n]+|\b(?:the|an?|of)\b|[.!_,?()-]|<[^<]*>")

    @classmethod
    def cleanup(cls, string):
        string = string.casefold()
        while True:
            newstr = cls.r_cleanup.sub(" ", string).strip()
            if newstr == string:
                break
            string = newstr
        return string

    def check(self, answer):
        answer = Question.cleanup(answer)
        if not answer or len(answer) < 1:
            return False
        expected = Question.cleanup(self.answer)
        ratio = SequenceMatcher(None, expected, answer).ratio()
        LOGGER.error("%s / %s / %.2f", answer, expected, ratio)
        return ratio >= self.ratio

    def __str__(self):
        return self.question


class Pool:
    def __init__(self):
        self.questions = list()

    def seed(self):
        try:
            res = requests.get("https://opentdb.com/api.php?amount=50").json()
            res = res["results"]
            for i in res:
                answer = unesc(i["correct_answer"])
                if i["type"] == "boolean":
                    question = "True of false: {}".format(unesc(i["question"]))
                else:
                    answers = list(unesc(a) for a in i["incorrect_answers"])
                    answers += answer,
                    random.shuffle(answers)
                    question = "{}\n[{}]".format(
                        unesc(i["question"]),
                        "] [".join(answers))
                question = "Trivia: {}".format(question)
                if len(question) > 300:
                    continue
                self.questions.append(Question(0, question, answer))
        except Exception:
            LOGGER.exception("failed to get opentdb questions")
        try:
            res = requests.get("http://jservice.io/api/random?count=50").json()
            for i in res:
                value = i.get("value", 0) or 1000
                if value > 800:
                    continue
                answer = i["answer"]
                question = i["question"]
                question = "Trivia: {}".format(question)
                if len(question) > 300:
                    continue
                self.questions.append(Question(0, question, answer))
        except Exception:
            LOGGER.exception("failed to get jservice questions")
        random.shuffle(self.questions)

    def get_question(self):
        if not self.questions:
            self.seed()
        if not self.questions:
            return None
        return self.questions.pop()

    @classmethod
    def question(cls):
        if not hasattr(cls, "instance"):
            cls.instance = cls()
        return cls.instance.get_question()


class Result(Enum):
    CORRECT = 1
    INCORRECT = 2
    WON = 0xff


class Game:
    def __init__(self, towin):
        self.towin = towin
        self.counts = Counter()
        self._question = None

    @property
    def question(self):
        if not self._question:
            self._question = Pool.question()
        return self._question

    def check(self, answerer, answer):
        if not self._question:
            raise ValueError("no question asked")
        if self._question.check(answer):
            self.counts[answerer] += 1
            if self.counts[answerer] >= self.towin:
                return Result.WON
            return Result.CORRECT
        return Result.INCORRECT

    def skip(self):
        self._question = None

    def __str__(self):
        def key(item):
            return item[1]

        scores = sorted(
            ((k, v) for k, v in self.counts.items()),
            key=key, reverse=True)
        scores = [
            "#{}: {} ({})".format(i + 1, k, v)
            for i, (k, v) in enumerate(scores)][:5]
        return "Leaders: {}".format(" ".join(scores))


class TriviaCommand(PulseCommand):
    interval = 5.0
    timeout = 30

    def __init__(self, *args, **kw):
        self.game = None
        self.deadline = 0
        super().__init__(*args, **kw)

    def handles(self, cmd):
        if cmd == "!trivia":
            return True
        return self.game is not None

    def __call__(self, cmd, remainder, msg):
        if not self.allowed(msg):
            return False

        if cmd == "!trivia":
            if self.game:
                self.post("{}", self.game)
                return True
            try:
                towin = max(1, int(remainder.strip()))
            except Exception:
                towin = 5
            self.deadline = 0
            self.game = Game(towin)
            self.post("Started a trivia with {} to win", towin)
            return True

        res = self.game.check(msg.nick, msg.msg)
        if res == Result.WON:
            self.game = None
            self.post("WE GOT A WINRAR! Congrats {}", msg.nick)
            return True

        if res == Result.CORRECT:
            self.deadline = 0
            self.post("Indeed, {}: {}", msg.nick, self.game.question.answer)
            self.game.skip()
            return True

        return False

    def onpulse(self, _):
        if not self.game:
            return
        if not self.deadline:
            self.deadline = time() + self.timeout
            self.post("{}", self.game.question)
            return
        if not self.deadline > time():
            self.post("Too slow! Answer: {}", self.game.question.answer)
            self.game.skip()
            self.deadline = 0
            return

if __name__ == "__main__":
    def main():
        game = Game(10)
        while True:
            print(game.question)
            i = input("Answer: ")
            if not i:
                break
            res = game.check("you", i)
            if res == Result.WON:
                print("YOU WINRAR!")
                break
            if res == Result.CORRECT:
                print("Good!", game)
            else:
                print("nope")
            game.skip()

    main()

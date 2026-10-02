"""最小示例：只写游戏规则，通过 SDK 使用 Harness 的公共能力。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'sdk/python'))
from quickplay import Game

game = Game()
target = game.config.get('gameOptions', {}).get('target', 4)
position = 0
try:
    while position < target and not game.stopped.is_set():
        state = dict(position=position, target=target)
        game.publish(state)
        response = game.ask(state, {'move': {'type': 'choice', 'instructions': 'Reach the target by advancing.',
                                           'criteria': {'advance': 'Move forward one step', 'wait': 'Remain here'}}})
        answers = response['answers']
        if answers['move']['choice'] == 'advance':
            position += 1
        game.record(dict(execution=dict(schema='quickplay-execution-v1', id=response['requestId'],
                                        status='applied', rawAnswers=answers, executedAnswers=answers,
                                        action=dict(command=answers['move']['choice'], disposition='accepted'))))
    game.publish(dict(position=position, target=target))
    game.finish('won')
except RuntimeError as error:
    if not game.stopped.is_set():
        game.finish('error', str(error))

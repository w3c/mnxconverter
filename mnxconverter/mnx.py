from fractions import Fraction
import json
from mnxconverter.score import *

NOTE_VALUE_BASES = {
    Fraction(16): 'duplexMaxima',
    Fraction(8): 'maxima',
    Fraction(4): 'longa',
    Fraction(2): 'breve',
    Fraction(1): 'whole',
    Fraction(1, 2): 'half',
    Fraction(1, 4): 'quarter',
    Fraction(1, 8): 'eighth',
    Fraction(1, 16): '16th',
    Fraction(1, 32): '32nd',
    Fraction(1, 64): '64th',
    Fraction(1, 128): '128th',
    Fraction(1, 256): '256th',
    Fraction(1, 512): '512th',
    Fraction(1, 1024): '1024th',
    Fraction(1, 2048): '2048th',
    Fraction(1, 4096): '4096th',
}
ACCIDENTAL_TYPES_FOR_EXPORT = {
    Note.ACCIDENTAL_SHARP: 'sharp',
    Note.ACCIDENTAL_NATURAL: 'natural',
    Note.ACCIDENTAL_FLAT: 'flat',
    Note.ACCIDENTAL_DOUBLE_SHARP: 'double-sharp',
    Note.ACCIDENTAL_DOUBLE_FLAT: 'double-flat',
    Note.ACCIDENTAL_NATURAL_SHARP: 'natural-sharp',
    Note.ACCIDENTAL_NATURAL_FLAT: 'natural-flat',
}
SLUR_SIDES_FOR_EXPORT = {
    Slur.SIDE_UP: 'up',
    Slur.SIDE_DOWN: 'down',
}
OCTAVE_SHIFT_TYPES_FOR_EXPORT = {
    Ottava.TYPE_8VA: '1',
    Ottava.TYPE_8VB: '-1',
    Ottava.TYPE_15MA: '2',
    Ottava.TYPE_15MB: '-2',
    Ottava.TYPE_22MA: '3',
    Ottava.TYPE_22MB: '-3',
}
ENDING_TYPES_FOR_EXPORT = {
    Ending.TYPE_START: 'start',
    Ending.TYPE_STOP: 'stop',
    Ending.TYPE_DISCONTINUE: 'discontinue',
}
SLUR_INCOMPLETE_LOCATIONS_FOR_EXPORT = {
    Slur.INCOMPLETE_TYPE_INCOMING: 'incoming',
    Slur.INCOMPLETE_TYPE_OUTGOING: 'outgoing',
}

def put_score(score) -> bytes:
    writer = MNXWriter(score)
    return writer.get_filedata()

class MNXWriter:
    """
    Helper class that tracks state during a single MNX writing.
    Not meant to be used to write multiple files.
    """
    def __init__(self, score):
        self.score = score

    def get_filedata(self) -> bytes:
        result = {
            'mnx': {'version': 1}
        }
        result['global'] = self.encode_global()
        result['parts'] = self.encode_parts()
        return json.dumps(result, indent=2, sort_keys=True).strip().encode('utf8')

    def encode_global(self):
        measures = []
        for bar in self.score.bars:
            measures.append(self.encode_measure_global(bar))
        return {
            'measures': measures
        }

    def encode_measure_global(self, bar):
        result = {}
        if bar.timesig and bar.timesig_changed():
            time_data = {
                'count': bar.timesig.count,
                'unit': bar.timesig.unit
            }
            if bar.timesig.display is not None:
                time_data['display'] = bar.timesig.display
            result['time'] = time_data
        if bar.keysig and bar.keysig_changed():
            result['key'] = {'fifths': bar.keysig.fifths}
        if bar.start_repeat:
            result['repeatStart'] = {}
        if bar.end_repeat:
            repeat_end = {}
            if bar.end_repeat > 2:
                repeat_end['times'] = bar.end_repeat
            result['repeatEnd'] = repeat_end
        if bar.start_ending:
            # TODO: 'duration'
            result['ending'] = {
                'numbers': bar.start_ending.numbers
            }
        return result

    def encode_parts(self):
        return list(self.encode_part(part) for part in self.score.parts)

    def encode_part(self, part):
        result = {}
        if part.name is not None:
            result['name'] = part.name
        result['measures'] = list(self.encode_part_measure(bar.bar_parts[part.part_id]) for bar in self.score.bars)
        return result

    def encode_part_measure(self, bar_part:BarPart):
        result = {
            'sequences': list(self.encode_sequence(sequence) for sequence in bar_part.sequences)
        }
        if bar_part.clefs:
            result['clefs'] = list(self.encode_positioned_clef(clef) for clef in bar_part.clefs)
        # TODO: Implement beams.
        return result

    def encode_sequence(self, sequence:Sequence):
        return {
            'content': list(self.encode_sequence_item(item) for item in sequence.items)
        }

    def encode_sequence_item(self, item:SequenceItem):
        if isinstance(item, Event):
            return self.encode_event(item)
        elif isinstance(item, Tuplet):
            return self.encode_tuplet(item)
        elif isinstance(item, SequenceDirection):
            return self.encode_sequence_direction(item)
        elif isinstance(item, GraceNoteGroup):
            return self.encode_grace_note_group(item)

    def encode_event(self, event):
        result = {}
        result['duration'] = self.encode_note_value(event.duration)
        if event.is_referenced:
            result['id'] = event.event_id
        if event.is_rest():
            result['rest'] = {}
        else:
            result['notes'] = list(self.encode_note(note) for note in event.event_items)
        if event.slurs:
            encoded_slurs = (self.encode_slur(slur) for slur in event.slurs)
            result['slurs'] = list(s for s in encoded_slurs if s is not None)
        if event.markings:
            result['markings'] = self.encode_event_markings(event.markings)
        return result

    def encode_note_value(self, duration:RhythmicDuration):
        result = {}
        try:
            result['base'] = NOTE_VALUE_BASES[duration.frac]
        except KeyError:
            raise ValueError(f'Invalid duration fraction {duration.frac}')
        if duration.dots:
            result['dots'] = duration.dots
        return result

    def encode_note(self, note:Note):
        result = {'pitch': self.encode_pitch(note.pitch)}
        if note.is_referenced:
            result['id'] = note.note_id
        if note.rendered_acc:
            result['accidentalDisplay'] = {'show': True}
        if note.tie:
            tie_data = {'target': note.tie.end_note.note_id}
            if note.tie.side is not None:
                tie_data['side'] = note.tie.side
            result['tie'] = tie_data
        return result

    def encode_pitch(self, pitch:Pitch):
        result = {
            'step': pitch.step,
            'octave': pitch.octave,
        }
        if pitch.alter: # Don't bother encoding a zero, because that's the default.
            result['alter'] = pitch.alter
        return result

    def encode_slur(self, slur:Slur):
        result = {}
        if slur.is_incomplete:
            try:
                result['location'] = SLUR_INCOMPLETE_LOCATIONS_FOR_EXPORT[slur.incomplete_type]
            except KeyError:
                # We got an unknown/missing slur.incomplete_type.
                # Rather than generating invalid markup, we just
                # return None.
                return None
        else:
            if slur.end_event_id is None:
                # Don't create the <slur>, because we don't have
                # enough data.
                return None
            result['target'] = slur.end_event_id
            if slur.start_note:
                result['startNote'] = slur.start_note
            if slur.end_note:
                result['endNote'] = slur.end_note
        if slur.side is not None:
            result['side'] = SLUR_SIDES_FOR_EXPORT[slur.side]
        return result

    def encode_event_markings(self, markings:list):
        result = {}
        for marking in markings:
            if isinstance(marking, AccentMarking):
                result['accent'] = {}
            elif isinstance(marking, BreathMarking):
                result['breath'] = {}
            elif isinstance(marking, SoftAccentMarking):
                result['softAccent'] = {}
            elif isinstance(marking, SpiccatoMarking):
                result['spiccato'] = {}
            elif isinstance(marking, StaccatissimoMarking):
                result['staccatissimo'] = {}
            elif isinstance(marking, StaccatoMarking):
                result['staccato'] = {}
            elif isinstance(marking, StressMarking):
                result['stress'] = {}
            elif isinstance(marking, StrongAccentMarking):
                result['strongAccent'] = {}
            elif isinstance(marking, TenutoMarking):
                result['tenuto'] = {}
            elif isinstance(marking, TremoloMarking):
                result['tremolo'] = {'marks': marking.marks}
            elif isinstance(marking, UnstressMarking):
                result['unstress'] = {}
        return result

    def encode_tuplet(self, tuplet:Tuplet):
        result = {
            'inner': {
                'duration': 'TODO',
                'multiple': tuplet.ratio.inner_numerator
            },
            'outer': {
                'duration': 'TODO',
                'multiple': tuplet.ratio.outer_numerator
            },
        }
        result['content'] = list(self.encode_sequence_item(item) for item in tuplet.items)
        return result

    def encode_sequence_direction(self, direction:SequenceDirection):
        if isinstance(direction, Ottava):
            return self.encode_ottava(direction)

    def encode_ottava(self, ottava:Ottava):
        return {
            'end': ottava.end_pos,
            'type': 'ottava',
            'value': OCTAVE_SHIFT_TYPES_FOR_EXPORT[ottava.shift_type],
        }

    def encode_grace_note_group(self, grace_note_group:GraceNoteGroup):
        return {
            'content': [self.encode_event(event) for event in grace_note_group.events],
            'type': 'grace'
        }

    def encode_positioned_clef(self, positioned_clef:PositionedClef):
        result = {
            'clef': self.encode_clef(positioned_clef.clef)
        }
        if positioned_clef.position.numerator != 0:
            result['position'] = self.encode_rhythmic_position(positioned_clef.position)
        return result

    def encode_clef(self, clef:Clef):
        return {
            'staffPosition': clef.staff_position,
            'sign': clef.sign
        }

    def encode_rhythmic_position(self, position:Fraction):
        return {
            "fraction": [position.numerator, position.denominator]
        }

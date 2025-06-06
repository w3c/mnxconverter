from fractions import Fraction

DEFAULT_KEYSIG = 0
NUM_PITCHES_IN_OCTAVE = 12
KEYSIG_PITCHES = (
    # Maps fifths to tuples of (step, alter)
    (0, ('C', 0)),
    (1, ('G', 0)),
    (2, ('D', 0)),
    (3, ('A', 0)),
    (4, ('E', 0)),
    (5, ('B', 0)),
    (6, ('F', 1)),
    (7, ('C', 1)),
    (-1, ('F', 0)),
    (-2, ('B', -1)),
    (-3, ('E', -1)),
    (-4, ('A', -1)),
    (-5, ('D', -1)),
    (-6, ('G', -1)),
    (-7, ('C', -1)),
)
KEYSIG_TO_PITCH = {k: v for k, v in KEYSIG_PITCHES}
PITCH_TO_KEYSIG = {v: k for k, v in KEYSIG_PITCHES}

class Score:
    def __init__(self):
        self.parts = []
        self.bars = []

    def get_event_measure_rhythmic_position(self, event):
        """
        Returns a MeasureRhythmicPosition for the given Event, or None
        if we can't find the Event in the Score.
        """
        for bar_idx, bar in enumerate(self.bars):
            for bar_part in bar.bar_parts.values():
                for sequence in bar_part.sequences:
                    metrical_pos = Fraction(0, 1)
                    for seq_event in sequence.iter_events():
                        if seq_event == event:
                            return MeasureRhythmicPosition(
                                bar_idx + 1,
                                RhythmicPosition(
                                    metrical_pos,
                                    0 # TODO: Support grace_index.
                                )
                            )
                        metrical_pos += seq_event.duration.frac
        return ''

    def get_event_containing_note(self, note):
        for bar in self.bars:
            for bar_part in bar.bar_parts.values():
                for sequence in bar_part.sequences:
                    for event in sequence.iter_events():
                        for event_item in event.event_items:
                            if event_item == note:
                                return event
        return None

class Part:
    def __init__(self, part_id=None, name=None, transpose=0):
        self.part_id = part_id
        self.name = name
        self.transpose = transpose

class Bar:
    def __init__(self, score, idx: int, timesig=None, keysig=None):
        self.score = score
        self.idx = idx # Zero-based index of this bar in the score.
        self.timesig = timesig # TimeSignature object, or None.
        self.keysig = keysig # KeySignature object, in concert pitch.
        self.start_repeat = False
        self.end_repeat = 0
        self.start_ending = None # Ending object.
        self.stop_ending = None # Ending object. TODO: Remove?
        self.bar_parts = {} # Maps part_ids to BarParts.

    def previous(self):
        return self.score.bars[self.idx - 1] if self.idx else None

    def timesig_changed(self):
        "Returns True if this Bar's timesig has changed since the last bar."
        if self.idx == 0:
            return True
        if self.timesig is None:
            return False
        prev = self.previous().timesig
        return prev is None or not prev.equals(self.timesig)

    def active_keysig(self):
        """
        Returns this Bar's active keysig.

        This is different from self.keysig, because self.keysig is not
        necessarily defined.
        """
        idx = self.idx
        while idx >= 0:
            bar = self.score.bars[idx]
            if bar.keysig is not None:
                return bar.keysig
            idx -= 1
        return KeySignature(DEFAULT_KEYSIG)

    def keysig_changed(self):
        "Returns True if this Bar's active keysig has changed since the last bar."
        return (self.idx == 0 and self.keysig and self.keysig.fifths != 0) or \
            (self.idx != 0 and self.previous().active_keysig() != self.active_keysig())

class BarPart:
    def __init__(self):
        self.sequences = []
        self.clefs = []

    def get_sequence(self, sequence_id):
        for sequence in self.sequences:
            if sequence.sequence_id == sequence_id:
                return sequence
        return None

    def get_or_create_sequence(self, sequence_id):
        sequence = self.get_sequence(sequence_id)
        if sequence is None:
            sequence = Sequence([], sequence_id)
            self.sequences.append(sequence)
        return sequence

class SequenceItem:
    """
    An object that can be in a SequenceContent. Examples:
        * Tuplet
        * SequenceDirection
        * Event
        * GraceNoteGroup
    """
    def __init__(self, parent):
        self.parent = parent # SequenceContent.

    def __repr__(self):
        return f'<{self.__class__.__name__}>'

    def insert_before(self, other_sequence_item):
        parent_items = self.parent.items
        idx = parent_items.index(self)
        parent_items.insert(idx, other_sequence_item)

class SequenceContent:
    """
    An object that can contain SequenceItems. Examples:
        * Sequence
        * Tuplet
    """
    def __init__(self, items):
        self.items = items # SequenceItem objects.

    def iter_events(self):
        for item in self.items:
            if isinstance(item, Event):
                yield item
            else:
                for event in item.iter_events():
                    yield event

    def find_item_idx_by_event(self, target):
        for i, item in enumerate(self.items):
            if isinstance(item, Event):
                if item == target:
                    return i
            else:
                for event in item.iter_events():
                    if event == target:
                        return i
        return None

    def fold_items(self, item_list, klass, **kwargs):
        start_idx = self.find_item_idx_by_event(item_list[0])
        end_idx = self.find_item_idx_by_event(item_list[-1])
        if start_idx is not None and end_idx is not None:
            folded_items = self.items[start_idx:end_idx+1]
            del self.items[start_idx:end_idx+1]
            new_parent = klass(self, folded_items, **kwargs)
            for item in folded_items:
                item.parent = new_parent
            self.items.insert(start_idx, new_parent)
            return True
        else:
            raise NotImplementedError("Could not fold items.")
        return False

    def set_tuplet(self, ratio, item_list):
        """
        For the given list of SequenceItem objects, which
        are assumed to be in this SequenceContent already,
        folds them into a single Tuplet.
        """
        self.fold_items(item_list, Tuplet, ratio=ratio)

class Sequence(SequenceContent):
    def __init__(self, items, sequence_id, beams=None):
        super().__init__(items)
        self.sequence_id = sequence_id # Unique within the BarPart. Can be empty string.
        self.beams = beams or []

    def get_last_event(self):
        for obj in reversed(self.items):
            if isinstance(obj, Event):
                return obj
        return None

class Tuplet(SequenceItem, SequenceContent):
    def __init__(self, parent, items, ratio):
        SequenceItem.__init__(self, parent)
        SequenceContent.__init__(self, items)
        self.ratio = ratio # TupletRatio object.

class TupletRatio:
    def __init__(self, outer_numerator, outer_denominator, inner_numerator, inner_denominator):
        self.outer_numerator = outer_numerator
        self.outer_denominator = outer_denominator
        self.inner_numerator = inner_numerator
        self.inner_denominator = inner_denominator

class GraceNoteGroup(SequenceItem):
    def __init__(self, parent):
        self.parent = parent # SequenceContent.
        self.events = []

class Event(SequenceItem):
    def __init__(self, parent, event_id, duration):
        SequenceItem.__init__(self, parent)
        self.event_id = event_id
        self.duration = duration # RhythmicDuration
        self.event_items = [] # EventItem objects.
        self.slurs = [] # Slur objects.

        # List of Marking objects. MNX uses a dictionary for this, hence enforcing
        # uniqueness for markings (e.g., only a single staccato for an event), but
        # we use a list here, so that we can catch duplicates and have the option
        # to raise an error or warning during conversion.
        self.markings = []

        self.is_referenced = False # True if this Event's event_id is referenced by another object in the Score.

    def is_rest(self):
        for event_item in self.event_items:
            if isinstance(event_item, Note):
                return False
        return True

class RhythmicPosition:
    def __init__(self, fraction, grace_index):
        self.fraction = fraction
        self.grace_index = grace_index

class MeasureRhythmicPosition:
    def __init__(self, measure, position):
        self.measure = measure
        self.position = position

class Marking:
    pass

class AccentMarking(Marking):
    pass

class BreathMarking(Marking):
    pass

class SoftAccentMarking(Marking):
    pass

class SpiccatoMarking(Marking):
    pass

class StaccatoMarking(Marking):
    pass

class StaccatissimoMarking(Marking):
    pass

class StressMarking(Marking):
    pass

class StrongAccentMarking(Marking):
    pass

class TenutoMarking(Marking):
    pass

class TremoloMarking(Marking):
    def __init__(self, marks:int):
        self.marks = marks

class UnstressMarking(Marking):
    pass

class Beam:
    def __init__(self):
        self.events = []
        self.children = []

class BeamHook:
    def __init__(self, event, is_forward):
        self.event = event
        self.is_forward = is_forward

class SequenceDirection(SequenceItem):
    pass

class Ottava(SequenceDirection):
    # These are arbitrary codes, used only internally.
    TYPE_8VA = 1
    TYPE_8VB = 2
    TYPE_15MA = 3
    TYPE_15MB = 4
    TYPE_22MA = 5
    TYPE_22MB = 6

    def __init__(self, parent, shift_type=None, end_pos=None):
        super().__init__(parent)
        self.shift_type = shift_type
        self.end_pos = end_pos

class Ending:
    # These are arbitrary codes, used only internally.
    TYPE_START = 1
    TYPE_STOP = 2
    TYPE_DISCONTINUE = 3

    def __init__(self, ending_type, numbers=None):
        self.ending_type = ending_type
        self.numbers = numbers

class EventItem:
    pass

class Note(EventItem):
    # These are arbitrary codes, used only internally.
    ACCIDENTAL_SHARP = 1
    ACCIDENTAL_NATURAL = 2
    ACCIDENTAL_FLAT = 3
    ACCIDENTAL_DOUBLE_SHARP = 4
    ACCIDENTAL_DOUBLE_SHARP = 5
    ACCIDENTAL_DOUBLE_FLAT = 6
    ACCIDENTAL_NATURAL_SHARP = 7
    ACCIDENTAL_NATURAL_FLAT = 8

    def __init__(self, score, note_id):
        self.score = score
        self.note_id = note_id
        self.pitch = None
        self.rendered_acc = None # None, or one of Note.ACCIDENTAL_*.
        self.ties = [] # Tie objects, for each tie that this Note starts.
        self.is_referenced = False # True if this Note's note_id is referenced by another object in the Score.

class Rest(EventItem):
    pass

class Tie:
    def __init__(self, start_note=None, end_note=None):
        self.start_note = start_note # Note or None.
        self.end_note = end_note # Note or None.
        self.side = None # None, 'up' or 'down'.

class Slur:
    # These are arbitrary codes, used only internally.
    SIDE_UP = 1
    SIDE_DOWN = 2
    def __init__(self, end_event_id=None, side=None, start_note=None, end_note=None):
        self.end_event_id = end_event_id
        self.side = side
        self.start_note = start_note
        self.end_note = end_note

class RhythmicDuration:
    def __init__(self, frac, dots=0):
        self.frac = frac # fractions.Fraction object.
        self.dots = dots

    def __eq__(self, other):
        return self.frac == other.frac and self.dots == other.dots

STEP_INTEGER_WHITE_KEYS = {
    0: 'C',
    2: 'D',
    4: 'E',
    5: 'F',
    7: 'G',
    9: 'A',
    11: 'B',
}

class Pitch:
    # Pitch objects don't know whether they're in concert or transposed.
    # They're agnostic. It's the responsibility of calling code to interpret
    # them correctly.
    def __init__(self, step: str, octave: int, alter: int=0):
        self.step = step # One of {'A', 'B', 'C', 'D', 'E', 'F', 'G'}.
        self.octave = octave
        self.alter = alter # 0, -1, 1, 2, -2

    def __repr__(self):
        return f'<Pitch {self.scientific_pitch_string()}>'

    def __eq__(self, other):
        return self.step == other.step and self.octave == other.octave and self.alter == other.alter

    @classmethod
    def from_midi_number(cls, midi_number, prefer_flat=True):
        octave = (midi_number // NUM_PITCHES_IN_OCTAVE) - 1
        step_integer = midi_number % NUM_PITCHES_IN_OCTAVE
        if step_integer in STEP_INTEGER_WHITE_KEYS:
            alter = 0
        else:
            if prefer_flat:
                step_integer = (step_integer + 1) % NUM_PITCHES_IN_OCTAVE
                alter = -1
            else:
                step_integer = (step_integer - 1 + NUM_PITCHES_IN_OCTAVE) % NUM_PITCHES_IN_OCTAVE
                alter = 1
        return cls(STEP_INTEGER_WHITE_KEYS[step_integer], octave, alter)

    def midi_number(self):
        # C4 = 60
        return (NUM_PITCHES_IN_OCTAVE * (self.octave + 1)) + self.step_integer() + self.alter

    def step_integer(self):
        return {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}[self.step]

    def accidental_string(self):
        return {0: '', 1: '#', 2: '##', -1: 'b', -2: 'bb'}[self.alter]

    def scientific_pitch_string(self):
        return f'{self.step}{self.accidental_string()}{self.octave}'

    def transpose_chromatic(self, semitones):
        """
        Returns a new Pitch object with the given chromatic
        transposition applied.
        """
        if not semitones:
            return self # No alteration needed.
        return Pitch.from_midi_number(self.midi_number() + semitones)

    def to_concert(self, part: Part):
        """
        Given a Part object that describes this Pitch's transposition,
        returns this Pitch in concert pitch, taking the Part's
        transposition into account.
        """
        return self.transpose_chromatic(part.transpose)

class TimeSignature:
    def __init__(self, count, unit, display=None):
        self.count = count # Top number
        self.unit = unit # Bottom number
        self.display = display # 'common', 'cut' or None

    def equals(self, other):
        return self.count == other.count and self.unit == other.unit and self.display == other.display

class KeySignature:
    def __init__(self, fifths):
        self.fifths = fifths

    def __eq__(self, other):
        return self.fifths == other.fifths

    @classmethod
    def from_pitch(cls, pitch: Pitch):
        try:
            fifths = PITCH_TO_KEYSIG[(pitch.step, pitch.alter)]
        except KeyError:
            # TODO: Try enharmonic equivalents.
            raise NotImplementedError(f"Pitch {pitch.scientific_pitch_string()} doesn't have a clear key signature")
        return cls(fifths)

    def pitch(self):
        step, alter = KEYSIG_TO_PITCH[self.fifths]
        # TODO: Octave is hard-coded to 4. It would be more elegant
        # to have a separate PitchClass class to represent abstract
        # pitch classes removed from a specific octave.
        return Pitch(step, 4, alter)

    def transpose_chromatic(self, semitones):
        if not semitones:
            return self # No alteration needed.
        return KeySignature.from_pitch(self.pitch().transpose_chromatic(semitones))

    def to_concert(self, part: Part):
        """
        Given a Part object that describes this KeySignature, returns
        this KeySignature in concert pitch, taking the Part's
        transposition into account.
        """
        return self.transpose_chromatic(part.transpose)

class Clef:
    def __init__(self, sign, staff_position:int):
        self.sign = sign
        self.staff_position = staff_position # 0 means "middle of staff"

class PositionedClef:
    def __init__(self, clef, position:Fraction):
        self.clef = clef
        self.position = position # Rhythmic position within the bar.

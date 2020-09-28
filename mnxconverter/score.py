from fractions import Fraction

DEFAULT_KEYSIG = 0

class Score:
    def __init__(self):
        self.parts = []
        self.bars = []

    def get_event_measure_location(self, event):
        """
        Returns the given Event's measure location, as defined here:
        https://w3c.github.io/mnx/specification/common/#measure-location
        """
        for bar_idx, bar in enumerate(self.bars):
            for bar_part in bar.bar_parts.values():
                for sequence in bar_part.sequences:
                    metrical_pos = Fraction(0, 1)
                    for seq_event in sequence.iter_events():
                        if seq_event == event:
                            return f'{bar_idx+1}:{metrical_pos.numerator}/{metrical_pos.denominator}'
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
    def __init__(self, part_id=None, name=None):
        self.part_id = part_id
        self.name = name

class Bar:
    def __init__(self, score, idx: int, timesig=None, keysig=None):
        self.score = score
        self.idx = idx # Zero-based index of this bar in the score.
        self.timesig = timesig
        self.keysig = keysig # In concert pitch.
        self.start_repeat = False
        self.end_repeat = 0
        self.start_ending = None # Ending object.
        self.stop_ending = None # Ending object.
        self.bar_parts = {} # Maps part_ids to BarParts.

    def previous(self):
        return self.score.bars[self.idx - 1] if self.idx else None

    def timesig_changed(self):
        "Returns True if this Bar's timesig has changed since the last bar."
        return self.idx == 0 or self.previous().timesig != self.timesig

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
        return DEFAULT_KEYSIG

    def keysig_changed(self):
        "Returns True if this Bar's active keysig has changed since the last bar."
        return self.idx == 0 or self.previous().active_keysig() != self.active_keysig()

class BarPart:
    def __init__(self):
        self.sequences = []
        self.directions = []

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
    def __init__(self, items, sequence_id):
        super().__init__(items)
        self.sequence_id = sequence_id # Unique within the BarPart. Can be empty string.

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

class Event(SequenceItem):
    def __init__(self, parent, event_id, duration):
        SequenceItem.__init__(self, parent)
        self.event_id = event_id
        self.duration = duration # RhythmicDuration
        self.event_items = [] # EventItem objects.
        self.slurs = [] # Slur objects.
        self.slur_ends = [] # IDs of Events that start slur(s) that end on this Event.

class Direction(SequenceItem):
    pass

class ClefDirection(Direction):
    def __init__(self, clef):
        self.clef = clef

class SequenceDirection(SequenceItem):
    pass

class OctaveShift(SequenceDirection):
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
        self.tie_end_note = None # ID of Note that ends a tie that starts on this Note.
        self.is_referenced = False # True if this Note's note_id is referenced by another object in the Score.

class Rest(EventItem):
    pass

class Slur:
    # These are arbitrary codes, used only internally.
    SIDE_UP = 1
    SIDE_DOWN = 2
    INCOMPLETE_TYPE_INCOMING = 1
    INCOMPLETE_TYPE_OUTGOING = 2
    def __init__(self, end_event_id=None, side=None, is_incomplete=None, incomplete_type=None, start_note=None, end_note=None):
        self.end_event_id = end_event_id
        self.side = side
        self.is_incomplete = is_incomplete
        self.incomplete_type = incomplete_type
        self.start_note = start_note
        self.end_note = end_note

class RhythmicDuration:
    def __init__(self, frac, dots=0):
        self.frac = frac # fractions.Fraction object.
        self.dots = dots

    def __eq__(self, other):
        return self.frac == other.frac and self.dots == other.dots

class Pitch:
    def __init__(self, step: str, octave: int, alter: int=0):
        self.step = step
        self.octave = octave
        self.alter = alter

    def __eq__(self, other):
        return self.step == other.step and self.octave == other.octave and self.alter == other.alter

class Clef:
    def __init__(self, sign, line):
        self.sign = sign
        self.line = line

from lxml import etree
from mnxconverter.score import *

MNX_COMMON_DOCTYPE = ''
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
    OctaveShift.TYPE_8VA: '-8',
    OctaveShift.TYPE_8VB: '8',
    OctaveShift.TYPE_15MA: '-15',
    OctaveShift.TYPE_15MB: '15',
    OctaveShift.TYPE_22MA: '-22',
    OctaveShift.TYPE_22MB: '22',
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
    writer = MNXCommonWriter(score)
    return writer.get_filedata()

class MNXCommonWriter:
    """
    Helper class that tracks state during a single MNX-Common writing.
    Not meant to be used to write multiple files.
    """
    def __init__(self, score):
        self.score = score
        xml = etree.XML('<mnx/>',
            etree.XMLParser(strip_cdata=False, remove_blank_text=True)
        )
        self.xml = xml

    def get_filedata(self) -> bytes:
        self.write_global()
        self.write_parts()
        return etree.tostring(self.xml,
            pretty_print=True,
            encoding='UTF-8',
            xml_declaration=True,
            doctype=MNX_COMMON_DOCTYPE,
        )

    def write_global(self):
        global_el = quick_element(self.xml, 'global')
        for bar in self.score.bars:
            global_el.append(self.get_measure_header(bar))

    def get_measure_header(self, bar):
        measure_el = etree.Element('measure')
        direction_els = []
        if bar.timesig and bar.timesig_changed():
            time_el = quick_element(None, 'time', attrs={
                'signature': microformat_timesig(bar.timesig),
            })
            direction_els.append(time_el)
        if bar.keysig and bar.keysig_changed():
            key_el = quick_element(None, 'key', attrs={
                'fifths': microformat_keysig(bar.keysig),
            })
            direction_els.append(key_el)
        if bar.start_repeat:
            repeat_el = quick_element(None, 'repeat', attrs={
                'type': 'start',
            })
            direction_els.append(repeat_el)
        if bar.start_ending:
            ending = bar.start_ending
            ending_el = quick_element(None, 'ending', attrs={
                'type': ENDING_TYPES_FOR_EXPORT[ending.ending_type],
                'number': ','.join(str(n) for n in ending.numbers),
            })
            direction_els.append(ending_el)
        if bar.stop_ending:
            ending = bar.stop_ending
            ending_el = quick_element(None, 'ending', attrs={
                'type': ENDING_TYPES_FOR_EXPORT[ending.ending_type],
            })
            direction_els.append(ending_el)
        if bar.end_repeat:
            repeat_el = quick_element(None, 'repeat', attrs={
                'type': 'end',
            })
            if bar.end_repeat > 2:
                repeat_el.attrib['times'] = str(bar.end_repeat)
            direction_els.append(repeat_el)
        if direction_els:
            directions_el = quick_element(measure_el, 'directions')
            for direction_el in direction_els:
                directions_el.append(direction_el)
        return measure_el

    def write_parts(self):
        for part in self.score.parts:
            self.write_part(part)

    def write_part(self, part):
        part_el = quick_element(self.xml, 'part')
        if part.name is not None:
            quick_element(part_el, 'part-name', part.name)
        for bar in self.score.bars:
            self.write_bar_part(part_el, bar, bar.bar_parts[part.part_id])

    def write_bar_part(self, part_el, bar, bar_part):
        measure_el = quick_element(part_el, 'measure')
        self.write_directions(measure_el, bar_part.directions)
        for sequence in bar_part.sequences:
            self.write_sequence(measure_el, sequence)

    def write_directions(self, measure_el, directions):
        if directions:
            directions_el = quick_element(measure_el, 'directions')
            for direction in directions:
                self.write_direction(directions_el, direction)

    def write_direction(self, directions_el, direction):
        if isinstance(direction, ClefDirection):
            quick_element(directions_el, 'clef', attrs={
                'sign': direction.clef.sign,
                'line': direction.clef.line,
            })

    def write_sequence(self, measure_el, sequence):
        sequence_el = quick_element(measure_el, 'sequence')
        self.write_sequence_items(sequence_el, sequence.items)

    def write_sequence_items(self, parent_el, items):
        for item in items:
            if isinstance(item, Event):
                self.write_event(parent_el, item)
            elif isinstance(item, Tuplet):
                self.write_tuplet(parent_el, item)
            elif isinstance(item, SequenceDirection):
                self.write_sequence_direction(parent_el, item)

    def write_event(self, parent_el, event):
        event_el = etree.Element('event')
        event_el.attrib['value'] = microformat_duration(event.duration)
        if event.slur_ends:
            event_el.attrib['id'] = event.event_id
        for item in event.event_items:
            if isinstance(item, Note):
                self.write_note(event_el, item)
            elif isinstance(item, Rest):
                quick_element(event_el, 'rest')
        for slur in event.slurs:
            self.write_slur(event_el, slur)
        parent_el.append(event_el)

    def write_slur(self, event_el, slur):
        slur_el = etree.Element('slur')
        if slur.is_incomplete:
            try:
                slur_el.attrib['location'] = SLUR_INCOMPLETE_LOCATIONS_FOR_EXPORT[slur.incomplete_type]
            except KeyError:
                # We got an unknown/missing slur.incomplete_type.
                # Rather than generating invalid markup, we just
                # return, hence not creating the <slur> in the
                # <event>.
                return
        else:
            if slur.end_event_id is None:
                # Don't create the <slur>, because we don't have
                # enough data.
                return
            slur_el.attrib['target'] = slur.end_event_id
            if slur.start_note:
                slur_el.attrib['start-note'] = slur.start_note
            if slur.end_note:
                slur_el.attrib['end-note'] = slur.end_note
        if slur.side is not None:
            slur_el.attrib['side'] = microformat_slur_side(slur.side)
        event_el.append(slur_el)

    def write_note(self, parent_el, note):
        note_el = etree.Element('note')
        note_el.attrib['pitch'] = microformat_pitch(note.pitch)
        if note.is_referenced:
            note_el.attrib['id'] = note.note_id
        if note.rendered_acc:
            note_el.attrib['accidental'] = microformat_accidental(note.rendered_acc)
        if note.tie_end_note:
            quick_element(note_el, 'tied', attrs={'target': note.tie_end_note})
        parent_el.append(note_el)

    def write_tuplet(self, parent_el, tuplet):
        tuplet_el = quick_element(parent_el, 'tuplet', attrs={
            'inner': f'{tuplet.ratio.inner_numerator}/{tuplet.ratio.inner_denominator}',
            'outer': f'{tuplet.ratio.outer_numerator}/{tuplet.ratio.outer_denominator}',
        })
        self.write_sequence_items(tuplet_el, tuplet.items)

    def write_sequence_direction(self, parent_el, direction):
        directions_el = quick_element(parent_el, 'directions')
        if isinstance(direction, OctaveShift):
            self.write_octave_shift(directions_el, direction)

    def write_octave_shift(self, directions_el, octave_shift):
        quick_element(directions_el, 'octave-shift', attrs={
            'type': microformat_octave_shift(octave_shift.shift_type),
            'end': octave_shift.end_pos,
        })

def microformat_timesig(timesig):
    return f'{timesig[0]}/{timesig[1]}'

def microformat_keysig(keysig):
    return str(keysig)

def microformat_duration(duration):
    "Converts RhythmicDuration to duration microsyntax."
    frac = duration.frac
    if frac > 1:
        if frac.denominator != 1:
            raise ValueError(f'Invalid duration fraction {frac}')
        result = f'*{frac.numerator}'
    else:
        if frac.numerator != 1:
            raise ValueError(f'Invalid duration fraction {frac}')
        result = f'/{frac.denominator}'
    if duration.dots:
        result += 'd' * duration.dots
    return result

def microformat_pitch(pitch):
    result = pitch.step
    alter = pitch.alter
    if alter > 0:
        result += '#' * alter
    elif alter < 0:
        result += 'b' * (alter * -1)
    result += str(pitch.octave)
    return result

def microformat_accidental(accidental):
    try:
        return ACCIDENTAL_TYPES_FOR_EXPORT[accidental]
    except KeyError:
        raise ValueError('Unsupported accidental')

def microformat_slur_side(slur_side):
    return SLUR_SIDES_FOR_EXPORT[slur_side]

def microformat_octave_shift(shift_type):
    return OCTAVE_SHIFT_TYPES_FOR_EXPORT[shift_type]

def quick_element(root, tag_name, text='', attrs=None):
    el = etree.Element(tag_name)
    if text:
        el.text = text
    if attrs:
        for k, v in attrs.items():
            el.attrib[k] = v
    if root is not None:
        root.append(el)
    return el

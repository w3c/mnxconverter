from fractions import Fraction
from io import BytesIO
from lxml import etree
import re
import zipfile
from mnxconverter.score import *

ZIP_CONTAINER_FILENAME = 'META-INF/container.xml'
RHYTHM_TYPES = {
    'breve': (2, 1),
    'whole': (1, 1),
    'half': (1, 2),
    'quarter': (1, 4),
    'quater': (1, 4), # Non-standard
    'eighth': (1, 8),
    'eigth': (1, 8), # Non-standard
    'quaver': (1, 8), # Non-standard
    '8th': (1, 8), # Non-standard
    'semiquaver': (1, 16), # Non-standard
    'sixteenth': (1, 16), # Non-standard
    '16th': (1, 16),
    '32nd': (1, 32),
    '32th': (1, 32), # Non-standard
    '64th': (1, 64),
    '128th': (1, 128),
    '256th': (1, 256),
    '512th': (1, 512),
    '1024th': (1, 1024),
}
ACCIDENTAL_TYPES_FOR_IMPORT = {
    'sharp': Note.ACCIDENTAL_SHARP,
    'natural': Note.ACCIDENTAL_NATURAL,
    'flat': Note.ACCIDENTAL_FLAT,
    'double-sharp': Note.ACCIDENTAL_DOUBLE_SHARP,
    'sharp-sharp': Note.ACCIDENTAL_DOUBLE_SHARP,
    'flat-flat': Note.ACCIDENTAL_DOUBLE_FLAT,
    'natural-sharp': Note.ACCIDENTAL_NATURAL_SHARP,
    'natural-flat': Note.ACCIDENTAL_NATURAL_FLAT,
}
SLUR_SIDES_FOR_IMPORT = {
    'above': Slur.SIDE_UP,
    'below': Slur.SIDE_DOWN,
}
OCTAVE_SHIFT_TYPES_FOR_IMPORT = {
    ('8', 'down'): Ottava.TYPE_8VA,
    ('8', 'up'): Ottava.TYPE_8VB,
    ('15', 'down'): Ottava.TYPE_15MA,
    ('15', 'up'): Ottava.TYPE_15MB,
    ('16', 'down'): Ottava.TYPE_15MA, # Non-standard
    ('16', 'up'): Ottava.TYPE_15MB, # Non-standard
    ('22', 'down'): Ottava.TYPE_22MA,
    ('22', 'up'): Ottava.TYPE_22MB,
}
ENDING_TYPES_FOR_IMPORT = {
    'start': Ending.TYPE_START,
    'stop': Ending.TYPE_STOP,
    'discontinue': Ending.TYPE_DISCONTINUE,
}
DEFAULT_KEYSIG = 0
DIVISION_DURATION_WHOLE_NOTE = 4 # MusicXML constant specifying how many <divisions> are in a whole note.

class NotationImportError(Exception):
    "Represents an import error before we know a file is MusicXML."
    pass

class NotationDataError(Exception):
    """
    Represents an import error after we've already determined
    a file is MusicXML.
    """
    pass

def get_score(filedata: bytes):
    """
    Returns a Score object for the given raw file data,
    which can be compressed or uncompressed MusicXML.

    Raises NotationImportError or NotationDataError
    in case of problems.
    """
    xml = get_musicxml_etree(filedata)
    xml = clean_musicxml(xml)
    return read_musicxml(xml)

def get_musicxml_etree(filedata: bytes):
    """
    Given file contents (either compressed MusicXML or raw MusicXML),
    returns an etree Element instance, taking care of unzipping if
    necessary.

    The result is not guaranteed to be MusicXML, but it is guaranteed
    to be valid (parseable) XML)
    """
    fp = BytesIO(filedata)
    parser = etree.XMLParser(resolve_entities=False) # resolve_entities prevents XXE attacks.
    if zipfile.is_zipfile(fp):
        zip_obj = zipfile.ZipFile(fp, 'r')
        try:
            container_fp = zip_obj.open(ZIP_CONTAINER_FILENAME)
        except KeyError:
            raise NotationImportError(f"Zip file is missing {ZIP_CONTAINER_FILENAME}.")
        try:
            container_xml = etree.XML(container_fp.read(), parser)
        except etree.XMLSyntaxError:
            raise NotationImportError(f"XML syntax error when parsing {ZIP_CONTAINER_FILENAME}.")
        try:
            rootfile_el = container_xml.xpath('rootfiles/rootfile')[0]
        except IndexError:
            raise NotationImportError(f"Missing 'rootfile' element in {ZIP_CONTAINER_FILENAME}.")
        try:
            musicxml_filename = rootfile_el.attrib['full-path']
        except KeyError:
            raise NotationImportError("Missing 'full-path' attribute on 'rootfile' element.")

        musicxml_string = None
        try:
            musicxml_string = zip_obj.open(musicxml_filename).read()
        except Exception:
            # If that failed, it could be that the inner filename used a
            # non-ASCII character, in which case the given `xml_filename`
            # might be different than the actual filename used within the
            # archive. To deal with this, we look at the list of inner
            # filenames and find the one that ends with .xml which is *not*
            # ZIP_CONTAINER_FILENAME.
            for name in zip_obj.namelist():
                if name.lower().endswith('.xml') and name != ZIP_CONTAINER_FILENAME:
                    try:
                        musicxml_string = zip_obj.open(name).read()
                    except Exception:
                        pass
        if musicxml_string is None:
            raise NotationImportError("Missing or empty MusicXML file within zip archive.")
    else:
        musicxml_string = filedata
    try:
        return etree.XML(musicxml_string, parser)
    except etree.XMLSyntaxError as e:
        raise NotationImportError(f"XML syntax error: {e.args[0]}")

def convert_to_timewise(xml):
    """
    Given a <score-partwise> MusicXML document as an etree
    Element, converts it to <score-timewise>. The object is changed
    in place, and it's also returned.

    Input has top-level <part> tags with <measure> tags within.
    Output has top-level <measure> tags with <part> tags within.
    """
    first_part = xml.find('part')
    if first_part is None:
        raise NotationImportError("Couldn't convert partwise to timewise.")

    xml.tag = 'score-timewise'

    new_measures = []
    for old_measure in first_part.iterfind('measure'):
        new_measure = etree.SubElement(xml, 'measure')
        new_measure.attrib.update(old_measure.attrib)
        new_measures.append(new_measure)

    for part in xml.iterfind('part'):
        for i, measure in enumerate(part.iterfind('measure')):
            try:
                new_measure = new_measures[i]
            except IndexError:
                continue # This measure wasn't in the first part. Skip!
            else:
                measure_part = etree.SubElement(new_measure, 'part')

            # The 'number' attribute is required by the spec,
            # but we tolerate it being missing. If it's missing,
            # we assume <measure> elements are in order, hence
            # using the value "i+1" to make the count one-based
            # instead of zero-based.
            measure_part.attrib['number'] = new_measure.attrib.get('number', str(i+1))

            measure_part.attrib.update(part.attrib)
            for sub_el in measure:
                measure_part.append(sub_el)
            part.remove(measure)
        xml.remove(part)

    return xml

def clean_musicxml(xml):
    if xml.tag == 'score-partwise':
        xml = convert_to_timewise(xml)
    elif xml.tag != 'score-timewise':
        raise NotationImportError("Didn't find 'score-partwise' or 'score-timewise'.")
    return xml

def read_musicxml(xml):
    reader = MusicXMLReader(xml)
    return reader.read()

class MusicXMLReader:
    """
    Helper class that tracks state during a single MusicXML parsing.
    Not meant to be used to parse multiple files.
    """
    def __init__(self, xml):
        self.xml = xml
        self.score = Score()
        self.part_divisions = {} # Maps part ID to current <divisions> value.
        self.open_ties = []
        self.current_beams = [] # List of (Sequence, Event, beam_data)
        self.open_beams = {} # Maps part ID to {beam_number: Beam} dictionaries.
        self.open_tuplets = {} # Maps MusicXML tuplet number to event_list.
        self.current_tuplets = [] # List of [sequence, event_list, ratio] lists.
        self.open_slurs = {} # Maps MusicXML slur number to [Slur, slur_start_attrs, slur_end_attrs, first_note, last_note].
        self.complete_slurs = [] # List of lists in the same format as self.open_slurs.
        self.current_grace_note_group = None # GraceNoteGroup object.
        self.next_event_id = 1
        self.next_note_id = 1
        self.current_octave_shift = None # [shift_type, note_list].
        self.complete_octave_shifts = []

    def read(self):
        self.parse_part_list()
        self.parse_measures()
        return self.score

    def parse_part_list(self):
        parts = self.score.parts
        part_list_el = self.xml.find('part-list')
        if part_list_el is not None:
            for score_part_el in part_list_el.iterfind('score-part'):
                part = self.parse_part(score_part_el)
                parts.append(part)

    def parse_part(self, score_part_el):
        try:
            part_id = score_part_el.attrib['id']
        except KeyError:
            raise NotationDataError(f"<score-part> on line {score_part_el.sourceline} is missing an 'id' attribute.")
        part_name_el = score_part_el.find('part-name')
        name = part_name_el.text if part_name_el is not None else None
        try:
            first_measure_el = self.xml.xpath('measure/part[@id=$partid]', partid=part_id)[0]
        except IndexError:
            transpose = 0
        else:
            transpose = self.parse_measure_transpose(first_measure_el)
        return Part(
            part_id=part_id,
            name=name,
            transpose=transpose
        )

    def parse_measure_transpose(self, measure_el):
        """
        Given the first <measure> element for a part, determines the
        part's transposition and returns it, as a chromatic value.
        """
        result = 0
        transpose_el = measure_el.find('attributes/transpose')
        if transpose_el is not None:
            chromatic_el = transpose_el.find('chromatic')
            if chromatic_el is not None and chromatic_el.text:
                try:
                    result += int(chromatic_el.text)
                except ValueError:
                    pass
            octave_change_el = transpose_el.find('octave-change')
            if octave_change_el is not None and octave_change_el.text:
                try:
                    result += int(octave_change_el.text) * 12
                except ValueError:
                    pass
        return result

    def parse_measures(self):
        score = self.score
        bars = score.bars
        parts = score.parts
        for idx, measure_el in enumerate(self.xml.iterfind('measure')):
            bar = Bar(score, idx)
            bars.append(bar)
            for part_idx, measure_part_el in enumerate(measure_el.iterfind('part')):
                self.parse_measure_part(measure_part_el, bar, parts[part_idx])

    def parse_measure_part(self, measure_part_el, bar, part):
        position = 0
        bar_part = BarPart()
        clef = None
        for el in measure_part_el:
            tag = el.tag
            if tag == 'attributes':
                clef = self.parse_measure_attributes(el, bar, part, bar_part, position)
            elif tag == 'backup':
                position -= self.parse_forward_backup(el)
            elif tag == 'barline':
                self.parse_barline(el, bar)
            elif tag == 'direction':
                self.parse_direction(el)
            elif tag == 'forward':
                position += self.parse_forward_backup(el)
            elif tag == 'note':
                position += self.parse_note(el, part, bar_part)
        bar.bar_parts[part.part_id] = bar_part

        # Handle the slurs. For each completed slur, we find the
        # corresponding Event for the start and end Notes, then
        # set the slur data on the two Events.
        if self.complete_slurs:
            for obj in self.complete_slurs:
                self.add_slur(*obj)
            self.complete_slurs.clear()

        # Handle the tuplets.
        for sequence, event_list, ratio in self.current_tuplets:
            sequence.set_tuplet(ratio, event_list)
        self.current_tuplets.clear()

        # Handle the beams.
        self.process_beams(part.part_id)

        # Handle the octave shifts.
        for shift_type, note_list in self.complete_octave_shifts:
            self.add_octave_shift(shift_type, note_list)
        self.complete_octave_shifts.clear()

    def parse_measure_attributes(self, attributes_el, bar, part, bar_part, position):
        for el in attributes_el:
            tag = el.tag
            if tag == 'clef':
                bar_part.clefs.append(self.parse_clef(part, el, position))
            elif tag == 'divisions':
                self.part_divisions[part.part_id] = self.parse_divisions(el)
            elif tag == 'key':
                bar.keysig = self.parse_key(el, part)
            elif tag == 'time':
                bar.timesig = self.parse_time(el)

    def parse_clef(self, part, clef_el, musicxml_position):
        sign = None
        line = None
        for el in clef_el:
            tag = el.tag
            if tag == 'sign':
                if el.text is not None:
                    sign = el.text
            elif tag == 'line':
                if el.text is not None:
                    line = el.text
        try:
            line = int(line)
        except ValueError:
            raise NotationDataError(f'<clef> on line {clef_el.sourceline} has invalid "line" value: "{line}".')

        # Convert MusicXML clef position (1 = bottom staff line)
        # to MNX staff_position (1 = middle staff line).
        # TODO: This assumes a five-line staff at the moment.
        staff_position = (2 * line) - 6

        rhythmic_position = Fraction(
            musicxml_position,
            self.part_divisions[part.part_id] * DIVISION_DURATION_WHOLE_NOTE
        )
        return PositionedClef(
            clef=Clef(
                sign=sign,
                staff_position=staff_position,
            ),
            position=rhythmic_position
        )

    def parse_divisions(self, divisions_el):
        try:
            return int(divisions_el.text)
        except ValueError:
            raise NotationDataError(f'<divisions> on line {divisions_el.sourceline} has invalid value "{divisions_el.text}".')

    def parse_barline(self, barline_el, bar):
        for el in barline_el:
            tag = el.tag
            if tag == 'ending':
                self.parse_ending(el, bar)
            elif tag == 'repeat':
                try:
                    direction = el.attrib['direction']
                except KeyError:
                    raise NotationDataError(f"<repeat> on line {el.sourceline} is missing a 'direction' attribute.")
                if direction == 'forward':
                    bar.start_repeat = True
                elif direction == 'backward':
                    try:
                        times = int(el.attrib['times'])
                    except (ValueError, KeyError):
                        times = 2
                    bar.end_repeat = times

    def parse_ending(self, el, bar):
        ending_type = el.attrib.get('type', None)
        if ending_type == 'start':
            if 'number' in el.attrib:
                numbers = [int(n) for n in re.split(r'[\s,]+', el.attrib['number']) if n.strip().isdigit()]
                if numbers:
                    bar.start_ending = Ending(
                        ENDING_TYPES_FOR_IMPORT[ending_type],
                        numbers
                    )
        elif ending_type in {'stop', 'discontinue'}:
            bar.stop_ending = Ending(ENDING_TYPES_FOR_IMPORT[ending_type])

    def parse_forward_backup(self, el):
        self.current_grace_note_group = None
        duration_el = el.find('duration')
        if duration_el is None:
            return 0
        return self.parse_duration(duration_el)

    def parse_direction(self, direction_el):
        for el in direction_el:
            tag = el.tag
            if tag == 'direction-type':
                self.parse_direction_type(el)

    def parse_direction_type(self, direction_type_el):
        for el in direction_type_el:
            tag = el.tag
            if tag == 'octave-shift':
                self.parse_octave_shift(el)

    def parse_octave_shift(self, el):
        type_ = el.attrib.get('type')
        if type_ in {'up', 'down'}:
            size = el.attrib.get('size', '8')
            if self.current_octave_shift is not None:
                # TODO: Close the current octave shift? Raise error?
                pass
            try:
                shift_type = OCTAVE_SHIFT_TYPES_FOR_IMPORT[(size, type_)]
            except KeyError:
                raise NotationDataError(f'<{el.tag}> on line {el.sourceline} has an unsupported type/size combination.')
            self.current_octave_shift = [shift_type, []]
        elif type_ == 'stop':
            if self.current_octave_shift is None:
                # TODO: Close the current octave shift? Raise error?
                pass
            else:
                if not self.current_octave_shift[1]:
                    # TODO: Raise error?
                    return
                self.complete_octave_shifts.append(self.current_octave_shift)
                self.current_octave_shift = None

    def parse_duration(self, el):
        try:
            return int(el.text)
        except ValueError:
            return 0 # TODO: Raise an error here?

    def parse_key(self, key_el, part: Part):
        "Parses <key>. Returns a KeySignature object in concert pitch."
        try:
            fifths = int(key_el.find('fifths').text)
        except (AttributeError, ValueError):
            fifths = DEFAULT_KEYSIG
        return KeySignature(fifths).to_concert(part)

    def parse_time(self, time_el):
        "Parses <time>. Returns timesig as a list."
        is_valid = True
        try:
            numerator = int(time_el.find('beats').text)
        except (AttributeError, ValueError, TypeError):
            is_valid = False
        try:
            denominator = int(time_el.find('beat-type').text)
        except (AttributeError, ValueError, TypeError):
            is_valid = False
        if not is_valid:
            if time_el.attrib.get('symbol') == 'common':
                numerator, denominator = 4, 4
            else:
                raise NotationDataError(f'<time> element on line {time_el.sourceline} contains invalid data.')
        return [numerator, denominator]

    def parse_note(self, note_el, part, bar_part):
        sequence_id = ''
        is_chord = False
        is_grace = False
        is_rest = False
        duration = None
        note_type = None
        num_dots = 0
        beams = []
        closed_tuplet_numbers = []
        event_markings = []
        time_mod = None
        note = Note(self.score, f'note{self.next_note_id}')
        for el in note_el:
            tag = el.tag
            if tag == 'accidental':
                try:
                    note.rendered_acc = ACCIDENTAL_TYPES_FOR_IMPORT[el.text]
                except KeyError:
                    raise NotationDataError(f'Got unsupported value "{el.text}" for <{tag}> on line {el.sourceline}.')
            elif tag == 'beam':
                beams.append(self.parse_beam(el))
            elif tag == 'chord':
                is_chord = True
            elif tag == 'dot':
                num_dots += 1
            elif tag == 'duration':
                duration = self.parse_duration(el)
            elif tag == 'grace':
                is_grace = True
            elif tag == 'notations':
                new_closed_tuplet_numbers, event_markings = self.parse_notations(el, note)
                if new_closed_tuplet_numbers:
                    closed_tuplet_numbers.extend(new_closed_tuplet_numbers)
            elif tag == 'pitch':
                note.pitch = self.parse_pitch(el)
            elif tag == 'rest':
                is_rest = True
            elif tag == 'time-modification':
                time_mod = self.parse_time_modification(el, note_type)
            elif tag == 'type':
                note_type = self.parse_type(el)
            elif tag == 'voice':
                sequence_id = el.text or ''

        # If <type> wasn't provided, we fall back to <duration>
        # to calculate the fractional value. This is likely a rest.
        if note_type is None:
            try:
                note_type = Fraction(
                    duration,
                    self.part_divisions[part.part_id] * DIVISION_DURATION_WHOLE_NOTE
                )
                num_dots = 0
            except Exception:
                raise NotationDataError(f'<note> on line {note_el.sourceline} is missing a valid <type> or <duration>.')

        rhythmic_duration = RhythmicDuration(note_type, num_dots)
        sequence = bar_part.get_or_create_sequence(sequence_id)
        if is_chord:
            event = sequence.get_last_event()
            if event:
                if rhythmic_duration and event.duration and event.duration != rhythmic_duration:
                    raise NotationDataError(f'Two separate <note>s within the same chord had different durations. One of the <note>s starts on line {note_el.sourceline}.')
            else:
                # TODO: Got a <note> with <chord> without a previous
                # <note> in the voice. Show an error? For now, we
                # effectively ignore the <chord> in this situation.
                event = Event(sequence, f'ev{self.next_event_id}', rhythmic_duration)
                self.next_event_id += 1
                sequence.items.append(event)
        else:
            event = Event(sequence, f'ev{self.next_event_id}', rhythmic_duration)
            self.next_event_id += 1
            if is_grace:
                if not self.current_grace_note_group:
                    self.current_grace_note_group = GraceNoteGroup(sequence)
                    sequence.items.append(self.current_grace_note_group)
                self.current_grace_note_group.events.append(event)
            else:
                self.current_grace_note_group = None
                sequence.items.append(event)

        if is_rest:
            event_item = Rest()
        else:
            if not note.pitch:
                raise NotationDataError(f'The <note> on line {note_el.sourceline} is missing <pitch>.')
            event_item = note
            self.next_note_id += 1

        event.event_items.append(event_item)
        if self.open_tuplets:
            for event_list in self.open_tuplets.values():
                event_list.append(event)
            for number in closed_tuplet_numbers:
                complete_tuplet = self.open_tuplets.pop(number)
                self.current_tuplets.append([sequence, complete_tuplet, time_mod])
        if beams:
            self.current_beams.append((sequence, event, beams))
        if self.current_octave_shift:
            self.current_octave_shift[1].append(event_item)
        if event_markings:
            event.markings.extend(event_markings)

        # Return the duration of this event, to increment our internal position.
        # We don't do this if is_chord==True, because we assume the first <note>
        # already incremented the position.
        if duration is not None and not is_chord:
            return duration
        else:
            return 0

    def parse_beam(self, beam_el):
        try:
            number = int(beam_el.attrib.get('number', 1))
        except ValueError:
            raise NotationDataError(f'<beam> on line {beam_el.sourceline} has an invalid "number" attribute.')
        return (number, beam_el.text)

    def parse_notations(self, notations_el, note):
        closed_tuplet_numbers = []
        event_markings = []
        for el in notations_el:
            tag = el.tag
            if tag == 'articulations':
                self.parse_articulations(el, event_markings)
            elif tag == 'ornaments':
                self.parse_ornaments(el, event_markings)
            elif tag == 'slur':
                self.parse_slur(el, note)
            elif tag == 'tied':
                tied_type = el.attrib.get('type')
                if tied_type == 'start':
                    self.open_ties.append(note)
                elif tied_type == 'stop':
                    # Find the Note that started this tie.
                    if not note.pitch:
                        raise NotationDataError(f'<tied> on line {el.sourceline} must come after <pitch> within <note>.')
                    start_note = self.get_open_tie_by_end_note(note)
                    if start_note:
                        start_note.tie_end_note = note.note_id
                        note.is_referenced = True
            elif tag == 'tuplet':
                closed_tuplet_number = self.parse_tuplet(el)
                if closed_tuplet_number:
                    closed_tuplet_numbers.append(closed_tuplet_number)
        return closed_tuplet_numbers, event_markings

    def parse_articulations(self, articulations_el, event_markings):
        for el in articulations_el:
            tag = el.tag
            if tag == 'accent':
                event_markings.append(AccentMarking())
            elif tag == 'breath-mark':
                event_markings.append(BreathMarking())
            elif tag == 'detached-legato':
                # MNX doesn't have the concept of a detached legato.
                # It's represented simply by a staccato + tenuto.
                event_markings.append(StaccatoMarking())
                event_markings.append(TenutoMarking())
            elif tag == 'soft-accent':
                event_markings.append(SoftAccentMarking())
            elif tag == 'spiccato':
                event_markings.append(SpiccatoMarking())
            elif tag == 'staccatissimo':
                event_markings.append(StaccatissimoMarking())
            elif tag == 'staccato':
                event_markings.append(StaccatoMarking())
            elif tag == 'stress':
                event_markings.append(StressMarking())
            elif tag == 'strong-accent':
                event_markings.append(StrongAccentMarking())
            elif tag == 'tenuto':
                event_markings.append(TenutoMarking())
            elif tag == 'unstress':
                event_markings.append(UnstressMarking())

    def parse_ornaments(self, ornaments_el, event_markings):
        for el in ornaments_el:
            tag = el.tag
            if tag == 'tremolo':
                if el.attrib.get('type', 'single') == 'single':
                    try:
                        marks = int(el.text)
                    except ValueError:
                        raise NotationDataError(f'<tremolo> on line {el.sourceline} has an invalid contents.')
                    event_markings.append(TremoloMarking(marks))

    def parse_slur(self, slur_el, note):
        slur_type = slur_el.attrib.get('type')
        try:
            slur_number = int(slur_el.get('number', 1))
        except (TypeError, ValueError):
            slur_number = 1
        if slur_type == 'start':
            try:
                side = SLUR_SIDES_FOR_IMPORT[slur_el.attrib.get('placement', '')]
            except KeyError:
                side = None
            self.open_slurs[slur_number] = [Slur(side=side), dict(slur_el.attrib), None, note, None]
        elif slur_type == 'stop':
            open_slurs = self.open_slurs
            try:
                open_slurs[slur_number][2] = dict(slur_el.attrib)
                self.open_slurs[slur_number][4] = note
            except KeyError:
                # Got <slur type="stop"> without matching <slur type="start">.
                # TODO: Raise an error?
                pass
            else:
                self.complete_slurs.append(self.open_slurs.pop(slur_number))

    def parse_tuplet(self, tuplet_el):
        """
        Parses <tuplet>. Returns the tuplet number if the tuplet
        is now closed. Else returns None.
        """
        result = None
        number = tuplet_el.attrib.get('number', '1')
        tuplet_type = tuplet_el.attrib.get('type')
        if tuplet_type == 'start':
            self.open_tuplets[number] = []
        elif tuplet_type == 'stop':
            result = number
        return result

    def parse_pitch(self, pitch_el):
        alter = 0
        step = None
        octave = None
        for el in pitch_el:
            tag = el.tag
            if tag == 'alter':
                try:
                    alter = int(el.text)
                except ValueError:
                    raise NotationDataError(f'<pitch> on line {pitch_el.sourceline} has an invalid <alter>.')
            elif tag == 'octave':
                try:
                    octave = int(el.text)
                except ValueError:
                    raise NotationDataError(f'<pitch> on line {pitch_el.sourceline} has an invalid <octave>.')
            elif tag == 'step':
                step = el.text
        if step is None:
            raise NotationDataError(f'<pitch> on line {pitch_el.sourceline} is missing <step>.')
        if octave is None:
            raise NotationDataError(f'<pitch> on line {pitch_el.sourceline} is missing <octave>.')
        return Pitch(step, octave, alter)

    def parse_time_modification(self, time_mod_el, note_type):
        actual_notes = None
        normal_notes = None
        normal_type = None
        num_dots = 0
        for el in time_mod_el:
            tag = el.tag
            if tag == 'actual-notes':
                if not (el.text and el.text.isdigit()):
                    raise NotationDataError(f'<time-modification> on line {time_mod_el.sourceline} has an invalid <{tag}>.')
                actual_notes = int(el.text)
            elif tag == 'normal-notes':
                if not (el.text and el.text.isdigit()):
                    raise NotationDataError(f'<time-modification> on line {time_mod_el.sourceline} has an invalid <{tag}>.')
                normal_notes = int(el.text)
            elif tag == 'normal-type':
                normal_type = self.parse_type(el)
            elif tag == 'normal-dot':
                num_dots += 1
        if normal_type is None:
            if note_type is None:
                raise NotationDataError(f'<{time_mod_el.tag}> on line {time_mod_el.sourceline} must come after <type>.')
            normal_type = note_type
        return TupletRatio(
            outer_numerator=normal_notes * normal_type.numerator,
            outer_denominator=normal_type.denominator,
            inner_numerator=actual_notes * normal_type.numerator,
            inner_denominator=normal_type.denominator,
        )

    def parse_type(self, type_el):
        text = type_el.text
        try:
            return Fraction(*RHYTHM_TYPES[text])
        except KeyError:
            raise NotationDataError(f'<type> on line {type_el.sourceline} got unsupported value "{text}".')

    def get_open_tie_by_end_note(self, end_note):
        for i, note in enumerate(self.open_ties):
            if note != end_note and note.pitch == end_note.pitch:
                del self.open_ties[i]
                return note
        return None

    def add_slur(self, slur, start_attrs, end_attrs, start_note, end_note):
        other_slurs = self.complete_slurs
        start_event = self.score.get_event_containing_note(start_note)
        end_event = self.score.get_event_containing_note(end_note)
        if start_event == end_event:
            # This is an "incomplete slur" -- one that starts and
            # ends on the same event. Determine whether it's incoming
            # or outgoing by looking at the "default-x" attribute on
            # the <slur type="start"> element. If it's negative,
            # we interpret that as incoming.
            slur.is_incomplete = True
            if re.match(r'-\d', start_attrs.get('default-x', '')):
                incomplete_type = Slur.INCOMPLETE_TYPE_INCOMING
            else:
                incomplete_type = Slur.INCOMPLETE_TYPE_OUTGOING
            slur.incomplete_type = incomplete_type
        else:
            slur.is_incomplete = False
            slur.end_event_id = end_event.event_id
            end_event.is_referenced = True

            # Check for slurs that are attached to specific notes,
            # as opposed to slurs that are attached to events.
            if self.heuristic_slur_targets_notes(slur, start_note, start_event, end_note, end_event, self.complete_slurs):
                slur.start_note = start_note.note_id
                slur.end_note = end_note.note_id
                start_note.is_referenced = True
                end_note.is_referenced = True

        start_event.slurs.append(slur)

    def process_beams(self, part_id):
        if part_id not in self.open_beams:
            self.open_beams[part_id] = {}
        part_open_beams = self.open_beams[part_id]
        pending_ends = []
        for sequence, event, beam_data in self.current_beams:
            event.is_referenced = True
            beam_data.sort() # Make sure beam numbers are in ascending order.
            for beam_number, beam_type in beam_data:
                if beam_type == 'begin':
                    beam = Beam()
                    beam.events.append(event)
                    part_open_beams[beam_number] = beam
                    if beam_number == 1:
                        sequence.beams.append(beam)
                    else:
                        try:
                            parent_beam = part_open_beams[beam_number - 1]
                        except KeyError:
                            raise NotationDataError(f'Got <beam number="{beam_number}"> outside of <beam number="{beam_number-1}">')
                        else:
                            parent_beam.children.append(beam)
                elif beam_type == 'continue':
                    try:
                        beam = part_open_beams[beam_number]
                    except KeyError:
                        pass # TODO: Error message.
                    else:
                        beam.events.append(event)
                elif beam_type == 'end':
                    try:
                        beam = part_open_beams[beam_number]
                    except KeyError:
                        pass # TODO: Error message.
                    else:
                        beam.events.append(event)
                        # Can't remove from part_open_beams yet, because
                        # there might be a secondary beam that relies
                        # on this.
                        pending_ends.append(beam_number)
                elif beam_type == 'forward hook' or beam_type == 'backward hook':
                    try:
                        parent_beam = part_open_beams[beam_number - 1]
                    except KeyError:
                        raise NotationDataError(f'Got <beam number="{beam_number}"> outside of <beam number="{beam_number-1}">')
                    else:
                        parent_beam.children.append(
                            BeamHook(event, beam_type == 'forward hook')
                        )
            if pending_ends:
                for beam_number in pending_ends:
                    part_open_beams.pop(beam_number)
                pending_ends = []
        self.current_beams = []

    def add_octave_shift(self, shift_type, note_list):
        # note_list is assumed to be in order.
        start_event = self.score.get_event_containing_note(note_list[0])
        end_event = self.score.get_event_containing_note(note_list[-1])
        start_event.insert_before(Ottava(
            start_event.parent,
            shift_type=shift_type,
            end_pos=self.score.get_event_measure_location(end_event),
        ))

    def heuristic_slur_targets_notes(self, slur, start_note, start_event, end_note, end_event, active_slurs):
        for slur_data in active_slurs:
            if slur_data[0] != slur:
                other_start_event = self.score.get_event_containing_note(slur_data[3])
                other_end_event = self.score.get_event_containing_note(slur_data[4])
                if other_start_event == start_event and other_end_event == end_event:
                    return True
        return False

import logging
import json
import newrelic.agent

from django.conf import settings
from django.core.urlresolvers import reverse
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import ugettext as _

from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from haystack.query import SQ

from notesapi.v1.models import Note
from notesapi.v1.serializers import NoteSerializer, NotesElasticSearchSerializer

if not settings.ES_DISABLED:
    from haystack.query import SearchQuerySet

log = logging.getLogger(__name__)


class AnnotationsLimitReachedError(Exception):
    """
    Exception when trying to create more than allowed annotations
    """
    pass


class AnnotationSearchView(GenericAPIView):
    """
    **Use Case**

        * Search and return a paginated list of annotations for a user.

            The annotations are always sorted in descending order by updated date.

            Each page in the list contains 25 annotations by default. The page
            size can be altered by passing parameter "page_size=<page_size>".

            Http400 is returned if the format of the request is not correct.

    **Search Types**

        * There are two types of searches one can perform

            * Database

                If ElasticSearch is disabled or text query param is not present.

            * ElasticSearch

    **Example Requests**

        GET /api/v1/search/
        GET /api/v1/search/?course_id={course_id}&user={user_id}

    **Query Parameters for GET**

        All the parameters are optional.

        * course_id: Id of the course.

        * user: Anonymized user id.

        * text: Student's thoughts on the quote

        * highlight: dict. Only used when search from ElasticSearch. It contains two keys:

            * highlight_tag: String. HTML tag to be used for highlighting the text. Default is "em"

            * highlight_class: String. CSS class to be used for highlighting the text.

    **Response Values for GET**

        * count: The number of annotations in a course.

        * next: The URI to the next page of annotations.

        * previous: The URI to the previous page of annotations.

        * current: Current page number.

        * num_pages: The number of pages listing annotations.

        * results: A list of annotations returned. Each collection in the list contains these fields.

            * id: String. The primary key of the note.

            * user: String. Anonymized id of the user.

            * course_id: String. The identifier string of the annotations course.

            * usage_id: String. The identifier string of the annotations XBlock.

            * quote: String. Quoted text.

            * text: String. Student's thoughts on the quote.

            * ranges: List. Describes position of quote.

            * tags: List. Comma separated tags.

            * created: DateTime. Creation datetime of annotation.

            * updated: DateTime. When was the last time annotation was updated.
    """

    def get(self, *args, **kwargs):  # pylint: disable=unused-argument
        """
        Search annotations in most appropriate storage
        """
        # search in DB when ES is not available or there is no need to bother it
        if settings.ES_DISABLED or 'text' not in self.request.query_params.dict():
            return self.get_from_db(*args, **kwargs)
        else:
            return self.get_from_es(*args, **kwargs)

    def get_from_db(self, *args, **kwargs):  # pylint: disable=unused-argument
        """
        Search annotations in database.
        """
        params = self.request.query_params.dict()
        query = Note.objects.filter(
            **{f: v for (f, v) in params.items() if f in ('course_id', 'usage_id')}
        ).order_by('-updated')

        if 'user' in params:
            query = query.filter(user_id=params['user'])

        if 'text' in params:
            query = query.filter(Q(text__icontains=params['text']) | Q(tags__icontains=params['text']))

        page = self.paginate_queryset(query)
        serializer = NoteSerializer(page, many=True)
        response = self.get_paginated_response(serializer.data)
        return response

    def get_from_es(self, *args, **kwargs):  # pylint: disable=unused-argument
        """
        Search annotations in ElasticSearch.
        """
        params = self.request.query_params.dict()
        query = SearchQuerySet().models(Note).filter(
            **{f: v for (f, v) in params.items() if f in ('user', 'course_id', 'usage_id')}
        )

        if 'text' in params:
            clean_text = query.query.clean(params['text'])
            query = query.filter(SQ(data=clean_text))

        if params.get('highlight'):
            opts = {
                'pre_tags': ['{elasticsearch_highlight_start}'],
                'post_tags': ['{elasticsearch_highlight_end}'],
                'number_of_fragments': 0
            }
            query = query.highlight(**opts)

        page = self.paginate_queryset(query)
        serializer = NotesElasticSearchSerializer(page, many=True)
        response = self.get_paginated_response(serializer.data)
        return response


class AnnotationListView(GenericAPIView):
    """
        **Use Case**

            * Get a paginated list of annotations for a user.

                The annotations are always sorted in descending order by updated date.

                Each page in the list contains 25 annotations by default. The page
                size can be altered by passing parameter "page_size=<page_size>".

                Http400 is returned if the format of the request is not correct.

            * Create a new annotation for a user.

                Http400 is returned if the format of the request is not correct.

        **Example Requests**

            GET /api/v1/annotations/?course_id={course_id}&user={user_id}

            POST /api/v1/annotations/

        **Query Parameters for GET**

            Both the course_id and user must be provided.

            * course_id: Id of the course.

            * user: Anonymized user id.

        **Response Values for GET**

            * count: The number of annotations in a course.

            * next: The URI to the next page of annotations.

            * previous: The URI to the previous page of annotations.

            * current: Current page number.

            * num_pages: The number of pages listing annotations.

            * results:  A list of annotations returned. Each collection in the list contains these fields.

                * id: String. The primary key of the note.

                * user: String. Anonymized id of the user.

                * course_id: String. The identifier string of the annotations course.

                * usage_id: String. The identifier string of the annotations XBlock.

                * quote: String. Quoted text.

                * text: String. Student's thoughts on the quote.

                * ranges: List. Describes position of quote.

                * tags: List. Comma separated tags.

                * created: DateTime. Creation datetime of annotation.

                * updated: DateTime. When was the last time annotation was updated.

        **Query Parameters for POST**

            user, course_id, usage_id, ranges and quote fields must be provided.

        **Response Values for POST**

            * id: String. The primary key of the note.

            * user: String. Anonymized id of the user.

            * course_id: String. The identifier string of the annotations course.

            * usage_id: String. The identifier string of the annotations XBlock.

            * quote: String. Quoted text.

            * text: String. Student's thoughts on the quote.

            * ranges: List. Describes position of quote in the source text.

            * tags: List. Comma separated tags.

            * created: DateTime. Creation datetime of annotation.

            * updated: DateTime. When was the last time annotation was updated.
    """

    serializer_class = NoteSerializer

    def get(self, *args, **kwargs):  # pylint: disable=unused-argument
        """
        Get paginated list of all annotations.
        """
        params = self.request.query_params.dict()

        if 'course_id' not in params:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        if 'user' not in params:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        notes = Note.objects.filter(course_id=params['course_id'], user_id=params['user']).order_by('-updated')
        page = self.paginate_queryset(notes)
        serializer = self.get_serializer(page, many=True)
        response = self.get_paginated_response(serializer.data)
        return response

    def post(self, *args, **kwargs):  # pylint: disable=unused-argument
        """
        Create a new annotation.

        Returns 400 request if bad payload is sent or it was empty object.
        """
        if not self.request.data or 'id' in self.request.data:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        try:
            total_notes = Note.objects.filter(
                    user_id=self.request.data['user'], course_id=self.request.data['course_id']
            ).count()
            if total_notes >= settings.MAX_NOTES_PER_COURSE:
                raise AnnotationsLimitReachedError

            note = Note.create(self.request.data)
            note.full_clean()

            # Gather metrics for New Relic so we can slice data in New Relic Insights
            newrelic.agent.add_custom_parameter('notes.count', total_notes)
        except ValidationError as error:
            log.debug(error, exc_info=True)
            return Response(status=status.HTTP_400_BAD_REQUEST)
        except AnnotationsLimitReachedError:
            error_message = _(
                u'You can create up to {max_num_annotations_per_course} notes.'
                u' You must remove some notes before you can add new ones.'
            ).format(max_num_annotations_per_course=settings.MAX_NOTES_PER_COURSE)
            log.info(
                u'Attempted to create more than %s annotations',
                settings.MAX_NOTES_PER_COURSE
            )

            return Response({
                'error_msg': error_message
            }, status=status.HTTP_400_BAD_REQUEST)

        note.save()

        location = reverse('api:v1:annotations_detail', kwargs={'annotation_id': note.id})
        serializer = NoteSerializer(note)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers={'Location': location})


class AnnotationDetailView(APIView):
    """
        **Use Case**

            * Get a single annotation.

            * Update an annotation.

            * Delete an annotation.

        **Example Requests**

            GET /api/v1/annotations/<annotation_id>
            PUT /api/v1/annotations/<annotation_id>
            DELETE /api/v1/annotations/<annotation_id>

        **Query Parameters for GET**

            HTTP404 is returned if annotation_id is missing.

            * annotation_id: Annotation id

        **Query Parameters for PUT**

            HTTP404 is returned if annotation_id is missing and HTTP400 is returned if text and tags are missing.

            * annotation_id: String. Annotation id

            * text: String. Text to be updated

            * tags: List. Tags to be updated

        **Query Parameters for DELETE**

            HTTP404 is returned if annotation_id is missing.

            * annotation_id: Annotation id

        **Response Values for GET**

            * id: String. The primary key of the note.

            * user: String. Anonymized id of the user.

            * course_id: String. The identifier string of the annotations course.

            * usage_id: String. The identifier string of the annotations XBlock.

            * quote: String. Quoted text.

            * text: String. Student's thoughts on the quote.

            * ranges: List. Describes position of quote.

            * tags: List. Comma separated tags.

            * created: DateTime. Creation datetime of annotation.

            * updated: DateTime. When was the last time annotation was updated.

        **Response Values for PUT**

            * same as GET with updated values

        **Response Values for DELETE**

            * HTTP_204_NO_CONTENT is returned
    """

    def get(self, *args, **kwargs):  # pylint: disable=unused-argument
        """
        Get an existing annotation.
        """
        note_id = self.kwargs.get('annotation_id')

        try:
            note = Note.objects.get(id=note_id)
        except Note.DoesNotExist:
            return Response('Annotation not found!', status=status.HTTP_404_NOT_FOUND)

        serializer = NoteSerializer(note)
        return Response(serializer.data)

    def put(self, *args, **kwargs):  # pylint: disable=unused-argument
        """
        Update an existing annotation.
        """
        note_id = self.kwargs.get('annotation_id')

        try:
            note = Note.objects.get(id=note_id)
        except Note.DoesNotExist:
            return Response('Annotation not found! No update performed.', status=status.HTTP_404_NOT_FOUND)

        try:
            note.text = self.request.data['text']
            note.tags = json.dumps(self.request.data['tags'])
            note.full_clean()
        except KeyError as error:
            log.debug(error, exc_info=True)
            return Response(status=status.HTTP_400_BAD_REQUEST)

        note.save()

        serializer = NoteSerializer(note)
        return Response(serializer.data)

    def delete(self, *args, **kwargs):  # pylint: disable=unused-argument
        """
        Delete an annotation.
        """
        note_id = self.kwargs.get('annotation_id')

        try:
            note = Note.objects.get(id=note_id)
        except Note.DoesNotExist:
            return Response('Annotation not found! No update performed.', status=status.HTTP_404_NOT_FOUND)

        note.delete()

        # Annotation deleted successfully.
        return Response(status=status.HTTP_204_NO_CONTENT)

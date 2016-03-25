from haystack.backends.elasticsearch_backend import (
    ElasticsearchSearchEngine as OrigElasticsearchSearchEngine,
    ElasticsearchSearchBackend as OrigElasticsearchSearchBackend,
    ElasticsearchSearchQuery)


class ElasticsearchSearchBackend(OrigElasticsearchSearchBackend):
    """
    Subclassed backend that insists on storing tags
    """
    def build_search_kwargs(self, *args, **kwargs):
        res = super(ElasticsearchSearchBackend, self).build_search_kwargs(*args, **kwargs)
        if 'highlight' in res:
            res['highlight']['fields']['tags'] = {'store': 'yes'}
        return res

    def _process_results(
            self, raw_results, highlight=False, result_class=None, distance_point=None, geo_sort=False
    ):
        """
        Overrides _process_results from Haystack's ElasticsearchSearchBackend to add highlighted tags to the result
        """
        result = super(ElasticsearchSearchBackend, self)._process_results(
            raw_results, highlight, result_class, distance_point, geo_sort
        )

        for i, raw_result in enumerate(raw_results.get('hits', {}).get('hits', [])):
            if 'highlight' in raw_result:
                result['results'][i].highlighted_tags = raw_result['highlight'].get('tags', '')

        return result


class ElasticsearchSearchEngine(OrigElasticsearchSearchEngine):
    backend = ElasticsearchSearchBackend
    query = ElasticsearchSearchQuery

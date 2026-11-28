import logging

from django.core.paginator import Page, Paginator
from django.http import Http404
from django.utils.decorators import method_decorator
from django.views.decorators.vary import vary_on_headers
from django.views.generic import TemplateView

from accounts.permissions import AdminRequiredMixin
from analytics.forms import LogSearchForm
from analytics.search import MAX_RESULT_WINDOW, LogSearchError, search_logs

logger = logging.getLogger(__name__)


@method_decorator(vary_on_headers("HX-Request", "HX-History-Restore-Request"), name="dispatch")
class LogSearchView(AdminRequiredMixin, TemplateView):
    
    template_name = "analytics/log_search.html"
    partial_template_name = "analytics/partials/log_search_content.html"
    paginate_by = 50

    def get_template_names(self):
        is_htmx = self.request.headers.get("HX-Request") == "true"
        is_history_restore = self.request.headers.get("HX-History-Restore-Request") == "true"
        if is_htmx and not is_history_restore:
            return [self.partial_template_name]
        return [self.template_name]

    def get_page_number(self):
        try:
            number = int(self.request.GET.get("page", 1))
        except ValueError:
            raise Http404("Invalid page number.")
        if number < 1 or (number - 1) * self.paginate_by >= MAX_RESULT_WINDOW:
            raise Http404("Invalid page number.")
        return number

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = LogSearchForm(self.request.GET)
        context["form"] = form

        query_params = self.request.GET.copy()
        query_params.pop("page", None)
        context["querystring"] = query_params.urlencode()

        if not form.is_valid():
            return context

        criteria = form.to_criteria()
        page_number = self.get_page_number()
        try:
            result = search_logs(criteria, page=page_number, per_page=self.paginate_by)
        except LogSearchError as error:
            logger.warning("Log search failed: %s", error)
            context["search_error"] = "Log search is unavailable right now. Please try again later."
            return context

        if not result.hits and page_number > 1:
            raise Http404("That page contains no results.")

        logger.info(
            "Log search: after=%s before=%s levels=%s text=%r page=%s results=%s by=%s",
            criteria.after.isoformat() if criteria.after else "-",
            criteria.before.isoformat() if criteria.before else "-",
            ",".join(criteria.levels) or "-",
            criteria.text,
            page_number,
            result.total,
            self.request.user.username,
        )

        # the hits of this page are already fetched so the paginator only needs the total
        paginator = Paginator(range(result.total), self.paginate_by)
        page = Page(result.hits, page_number, paginator)
        context.update(
            result=result,
            entries=result.hits,
            criteria=criteria,
            paginator=paginator,
            page_obj=page,
            is_paginated=paginator.num_pages > 1,
        )
        return context

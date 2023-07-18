__author__ = "Suyash Soni"
__email__ = "suyash.soni248@gmail.com"

from sqlalchemy import or_, and_
from .criterion import Criterion
from ..constants.error_codes import ErrorCode
from ..commons import commons
from ..commons.error_handlers.exceptions.exceptions import ExceptionBuilder, SqlAlchemyException

class Search():
    """
    SQL-alchemy JSON query builder. Constructs queryset via JSON and that queryset can be used to get the results.
    """
    def __init__(self, session, model_module, model_classes, filter_by=[], order_by=(), page=1, per_page=10, all=False,
                 window_size=None):
        """
        :param model_classes: Tuple/list of model types/classes on which filtering has to be done.
        :param filter_by: dict containing `field_name`, `field_value` & `operator` as shown above.
        :param model_module: Name of the module/package where all the models are placed.
        :param order_by: list containing `field_name`s. `-` sign denotes DESC order.
        :param page: Current page number.
        :param per_page: Number of records to be shown on a page.
        :param all: if `True`, returns all searched results without pagination.
        :param window_size: Defines the number of records to be fetched from db at a time.
        :return: {data: [<filtered_records>], count: <num_of_records>}
        """
        self.model_classes = model_classes
        self.filter_by = filter_by
        self.order_by = order_by
        self.page = page
        self.per_page = per_page
        self.all = all
        self.window_size = window_size
        self.session = session
        self.model_module = model_module

    @property
    def results(self):
        """
        Fires/executes query on underlying **queryset** and fetch `results(data)` and `count`. if **self.all** is False then
        `results` will be paginated.
        :return: Dict containing `data` i.e. paginated results & `count` i.e. total number of records.
        """
        query_set = self.query()
        count = query_set.count()
        if not self.all:
            start, stop = self.per_page * (self.page - 1), self.per_page * self.page
            query_set = query_set.slice(start, stop)
        return {
            "data": query_set.all(),
            "count": count
        }

    def __eval_criterion__(self, field_name, field_value, operator):
        """
        Recursively creates and evaluates criteria. e.g. Following JSON will be translated to -
        {
			"field_name": "NotificationGroup.group_mappings",
			"field_value": {
				"field_name": "NotificationGroupMapping.recipient",
				"field_value": {
					"field_name": "Recipient.recipient_email",
					"field_value": "Samson",
					"operator": "contains"
				},
				"operator": "has"
			},
			"operator": "any"
		}

        This query -

        res = db.session.query(NotificationGroup).filter(
            NotificationGroup.group_mappings.any(
                NotificationGroupMapping.event.has(
                    Event.denotation == "Den2"
                )
            ).all()

        `More info` - http://docs.sqlalchemy.org/en/latest/orm/tutorial.html#common-relationship-operators
        """
        m_cls_name = field_name[:field_name.rindex('.')]
        field_name = field_name[field_name.rindex('.')+1:]
        m_cls = commons.load_class('{}.{}'.format(self.model_module,  m_cls_name))

        if type(field_value) == dict:
            field_value = self.__eval_criterion__(field_value['field_name'], field_value['field_value'], field_value['operator'])
        criterion = Criterion(m_cls, field_name, field_value, operator)
        return criterion.eval()

    def __eval_criteria__(self, criteria=()):
        expressions = []
        error_fields = []
        if not isinstance(criteria, (list, tuple, set)): criteria = [criteria]
        for criterion in criteria:
            try:
                evaluated_criterion = self.__eval_criterion__(criterion.get('field_name'), criterion.get('field_value'),
                                                              criterion.get('operator'))
                expressions.append(evaluated_criterion)
            except AttributeError as ae:
                error_fields.append(criterion.get('field_name', 'unknown'))
        return expressions, error_fields

    def query(self):
        """
        Constructs SQL-alchemy queryset via JSON.
        :return: SQL-alchemy queryset.
        """
        data_query_set = self.session.query(*self.model_classes)

        if isinstance(self.filter_by, list):
            data_query_set = data_query_set.filter(self.__build_expressions__(self.filter_by))
        else:
            or_filter = self.filter_by.get('or', [])
            and_filter = self.filter_by.get('and', [])
            or_expression = self.__build_expressions__({'or': or_filter})
            and_expression = self.__build_expressions__({'and': and_filter})
            data_query_set = data_query_set.filter(or_(or_expression), and_(and_expression))

        ordering_criteria = self.order_by or []

        order_by_expressions = []
        for ordering_criterion in ordering_criteria:
            direction = 'desc' if ordering_criterion.startswith('-') else 'asc'
            model_cls_field_name = ordering_criterion.replace('-', '', 1)
            m_cls_name = model_cls_field_name[:model_cls_field_name.rindex('.')]
            field_name = model_cls_field_name[model_cls_field_name.rindex('.') + 1:]
            m_cls = commons.load_class('{}.{}'.format(self.model_module,  m_cls_name))
            model_field = getattr(m_cls, field_name)
            order_by_expressions.append(getattr(model_field, direction)())

        data_query_set = data_query_set.order_by(*order_by_expressions)
        return data_query_set

    def __build_expressions__(self, filter_by):
        if isinstance(filter_by, (list, tuple, set)):
            filter_by = {'and': [query_obj for query_obj in filter_by]}

        logical_operators = {
            'and': (self.__build_sql_sequence__, and_),
            'or': (self.__build_sql_sequence__, or_)
        }

        operator = list(filter_by.keys())[0]

        if operator in logical_operators:
            builder, func = logical_operators[operator]
            return builder(filter_by[operator], func)
        else:
            expressions, error_fields = self.__eval_criteria__(filter_by)
            if len(error_fields) > 0:
                ExceptionBuilder(SqlAlchemyException).error(ErrorCode.INVALID_FIELD, *error_fields).throw()

            return expressions

    def __build_sql_sequence__(self, node, func):
        subqueries = []
        for value in node:
            subquery = self.__build_expressions__(value)
            subqueries.extend(subquery) if isinstance(subquery, list) else subqueries.append(subquery)

        return func(*subqueries)

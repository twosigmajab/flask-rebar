import marshmallow
from marshmallow import ValidationError
from marshmallow import fields
from marshmallow import post_dump
from marshmallow import validates_schema
from marshmallow.base import FieldABC, SchemaABC
from marshmallow.validate import Regexp

from plangrid.flask_toolbox import messages


def ValidateBothWays(field_or_schema):
    """Validate data on serialization.

    Shortcut for inheriting from the class & wrapping the relevant method.
    """
    class_name = 'ValidateBothWays' + field_or_schema.__name__
    klass = type(class_name, (field_or_schema,), {})

    if issubclass(field_or_schema, FieldABC):
        def wrapped_serialize(self, value, attr, obj):
            self.deserialize(value)
            return super(klass, self)._serialize(value, attr, obj)

        klass._serialize = wrapped_serialize
    elif issubclass(field_or_schema, SchemaABC):
        def wrapped_dump(self, object, **kwargs):
            unchecked = super(klass, self).dump(object, **kwargs)
            load = super(klass, self).load(unchecked.data)
            unchecked.errors.update(load.errors)
            return unchecked

        klass.dump = wrapped_dump
    else:
        raise ValueError('Unkown type for ValidateBothWays', field_or_schema)

    return klass


class IsObjectId(Regexp):
    def __init__(self):
        super(IsObjectId, self).__init__(
            regex='[0-9a-fA-F]{24}$',
            flags=0,
            error=messages.invalid_object_id
        )

    def __call__(self, value):
        super(IsObjectId, self).__call__(str(value))


class ObjectId(ValidateBothWays(fields.String)):
    """A string ObjectId field.

    Honors the inherited allow_none keyword argument, but raises an error if you
    try to specify the validate keyword argument.
    """
    def __init__(self, **kwargs):
        super(ObjectId, self).__init__(validate=IsObjectId(), **kwargs)


class IsUUID(Regexp):
    def __init__(self):
        super(IsUUID, self).__init__(
            regex='[0-9A-Fa-f]{8}-([0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}$',
            flags=0,
            error=messages.invalid_uuid
        )

    def __call__(self, value):
        super(IsUUID, self).__call__(str(value))


class UUID(ValidateBothWays(fields.String)):
    """A string UUID field.

    Honors the inherited allow_none keyword argument, but raises an error if you
    try to specify the validate keyword argument.
    """
    def __init__(self, **kwargs):
        super(UUID, self).__init__(validate=IsUUID(), **kwargs)


class CommaSeparatedList(fields.List):
    def _deserialize(self, value, attr, data):
        items = value.split(',')
        return super(CommaSeparatedList, self)._deserialize(items, attr, data)

    def _serialize(self, value, attr, obj):
        items = super(CommaSeparatedList, self)._serialize(value, attr, obj)
        return ','.join([str(i) for i in items])


class QueryParamList(fields.List):
    """
    A field class for Marshmallow; use this class when your list will be
    deserialized from a query string containing the same param multiple
    times where each param is an item in the list.
    e.g. ?foo=bar&foo=baz -> {'foo': ['bar', 'baz']}
    """
    def _deserialize(self, value, attr, data):
        # data is a MultiDict of query params, so pull out all of the items
        # with getlist instead of just the first
        items = data.getlist(attr)
        return super(QueryParamList, self)._deserialize(items, attr, data)


class ActuallyRequireOnDumpMixin(object):
    @post_dump()
    def require_output_fields(self, data):
        for field_name in self.fields:
            field = self.fields[field_name]
            if field.required:
                if field_name not in data:
                    raise ValidationError(messages.required_field_missing(field_name))
                elif field.allow_none is False and data[field_name] is None:
                    raise ValidationError(messages.required_field_empty(field_name))


class DisallowExtraFieldsMixin(object):
    @validates_schema(pass_original=True)
    def disallow_extra_fields(self, processed_data, original_data):
        # If the input data isn't a dict just short-circuit and let the Marshmallow unmarshaller
        # raise an error.
        if not isinstance(original_data, dict):
            return

        input_fields = original_data.keys()
        expected_fields = list(self.fields) + [
            field.load_from
            for field in self.fields.values()
            if field.load_from is not None
        ]
        excluded_fields = self.exclude
        unsupported_fields = set(input_fields) - set(expected_fields) - set(excluded_fields)
        if len(unsupported_fields) > 0:
            raise ValidationError(message=messages.unsupported_fields(unsupported_fields))


def ListOf(schema, additional_fields=None):
    class_name = 'ListOf' + schema.__name__

    schema_fields = {
        'data': fields.Nested(schema, many=True)
    }
    if additional_fields:
        schema_fields.update(additional_fields)

    klass = type(class_name, (marshmallow.Schema,), schema_fields)

    if hasattr(schema, '__swagger_title__'):
        setattr(
            klass,
            '__swagger_title__',
            'ListOf' + getattr(schema, '__swagger_title__')
        )

    return klass


def PaginatedListOf(schema):
    pagination_fields = {
        'total_count': fields.Integer(),
        'next_page_url': fields.URL(allow_none=True)
    }
    return ListOf(schema=schema, additional_fields=pagination_fields)


def add_custom_error_message(base_class, field_validation_error_function):
    """
    Creates a Marshmallow field class that returns a custom
    validation error message.

    :param marshmallow.fields.Field base_class:
      Marshmallow field class
    :param field_validation_error_function:
      A function that takes one value argument and returns a string
    :return: A new Marshmallow field class
    """
    class CustomErrorMessageClass(base_class):
        def _deserialize(self, value, attr, data):
            try:
                return super(CustomErrorMessageClass, self)._deserialize(value, attr, data)
            except ValidationError:
                raise ValidationError(field_validation_error_function(value))

        def _validate(self, value):
            try:
                super(CustomErrorMessageClass, self)._validate(value)
            except ValidationError:
                raise ValidationError(field_validation_error_function(value))
    return CustomErrorMessageClass


class RequestSchema(DisallowExtraFieldsMixin, marshmallow.Schema):
    pass


class ResponseSchema(ActuallyRequireOnDumpMixin, marshmallow.Schema):
    pass


class Error(ResponseSchema):
    message = fields.String(required=True)
    code = fields.String(required=False)
    details = fields.Dict(required=False)
    errors = fields.Dict(required=False)
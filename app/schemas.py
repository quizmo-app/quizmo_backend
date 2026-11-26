from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class SchemaApi(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CoursImporte(SchemaApi):
    id_cours: int
    id_version: int
    nb_pages: int


class CoursResume(SchemaApi):
    id_cours: int
    titre: str
    version: int
    nb_pages: int
    nb_quiz: int
